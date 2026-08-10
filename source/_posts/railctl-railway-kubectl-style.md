---
title: "railctl: Railway, kubectl-style"
date: 2026-08-05 10:00:00
categories:
  - Blogs
tags:
  - railway
  - kubectl
  - infrastructure-as-code
  - go
banner: /images/posts/railctl-railway-kubectl-style/railctl-banner.png
cover: /images/posts/railctl-railway-kubectl-style/railctl-banner.png
description: "Railway solved deployment. railctl is for what happens after — declarative manifests, real diffs, and CI that can tell you what is about to change."
---

If you've ever run `kubectl apply` and wished Railway worked the same way, this
one's for you.

![railctl — Railway, kubectl-style](/images/posts/railctl-railway-kubectl-style/railctl-banner.png)

You saw the boat and assumed this was a migration tool — something to get you
_off_ Railway. It isn't.

railctl doesn't move you anywhere. It sits on top of Railway and gives you a
second way to drive it.

And if you've spent time administering Kubernetes, you already know this tool:

| railctl (Railway)              | kubectl (K8s)          |
| ------------------------------ | ---------------------- |
| `railctl apply -f stack.yaml`  | `kubectl apply -f`     |
| `railctl diff -f stack.yaml`   | `kubectl diff`         |
| `railctl exec web -- sh`       | `kubectl exec`         |
| `railctl port-forward db 5432` | `kubectl port-forward` |

Same verbs. Same shapes. Pointed at Railway instead of a cluster.

<!-- more -->

---

## First, what Railway actually is

If you haven't used it: [Railway](https://railway.app) is a deployment platform.Point it at a GitHub repo or a Docker image and it builds, deploys, and runs it no Dockerfile required if you don't want one, no cluster to manage, no YAML to learn on day one.

It gives you managed services like Postgres, Redis, MySQL and Mongo as one-click services. Private networking between services in a project. Persistent volumes. Custom domains with automatic TLS. Environments (production, staging, PR previews) that you can fork.

It is, genuinely, one of the best developer experiences in the deployment space. People pick Railway because in ten minutes you have a running app with a database attached, and you didn't have to think about infrastructure once.

This post is not an argument against any of that. Railway solved deployment. What follows is about what happens _after_ — when the project stops being a weekend thing and becomes something a team operates.

---

## The Railway CLI, doing its job

Railway ships a CLI, and it's substantial. Not a thin wrapper — a real tool:

```
add          Add a service to your project
connect      Connect to a database's shell (psql, mongosh, etc.)
logs         View build, deploy, HTTP, network flow, or DNS logs
metrics      View resource and HTTP metrics for a service
ssh          Connect to a service via SSH
domain       Add, list, inspect, update, or delete domains
tcp-proxy    Manage public TCP proxies
sandbox      Manage ephemeral sandboxes
run          Run a local command using variables from the active environment
up           Upload and deploy project from the current directory
```

That's a well-equipped operational toolkit. Database shells, logs, metrics, SSH into a running service — Railway covers day-two operations properly, and any comparison that pretends otherwise isn't worth reading.

It works, it's fast, and for a developer on a laptop it's a good experience.

---

## Then you put it in a pipeline

Here's where the shape of the tool starts to matter.

The Railway CLI is built around a **linked project** — a local association between the directory you're standing in and a project on Railway. `railway link` creates it. Most commands assume it. That's an excellent assumption on a laptop. It's a strange one in CI, where every run starts in a freshly cloned directory that has never been linked to anything.

Watch what happens in a directory with no link:

```
$ railway status
No linked project found. Run railway link to connect to a project
  → Run `railway link` to connect to a project.

$ railway up --ci
--workspace required in non-interactive mode (multiple workspaces available)
```

A fresh CI runner _is_ that directory, every single time.

There are answers — you can pass `--project`, `--environment`, `--service` explicitly, or use a project-scoped token that carries its own context. But the answer isn't obvious, and the evidence that it isn't obvious is public:

- **"Project Token not found"** in GitHub Actions is one of the most persistent questions in Railway's community — spanning [StackOverflow](https://stackoverflow.com/questions/79583273/railway-cli-deployment-in-github-actions-failing-with-project-token-not-found), [Railway Station](https://station.railway.com/questions/deploy-using-ci-cd-github-actions-18407bf0), and the [CLI issue tracker](https://github.com/railwayapp/cli/issues/105). The usual root cause is a missing link step.

- **CLI 5.3.0 changed token handling in non-interactive environments**, and pipelines broke. The [community thread](https://station.railway.com/questions/railway-cli-5-3-0-breaks-git-hub-actions-3f12fa24) contains _contradictory_ fixes — `RAILWAY_API_KEY` in one answer, `RAILWAY_TOKEN` plus explicit flags in another.

- **Linking in CI can hit rate limits.** Railway's own support [told a user](https://station.railway.com/questions/cicd-link-project-ratelimited-53840ce4) their pipeline was exhausting limits through repeated link calls, and suggested skipping the CLI.

And deploys are per-service. `railway up --service <SERVICE>` takes one service, defaulting to the linked one. Four services means four invocations, and the ordering between them is yours to manage.

None of this is broken. It's a tool designed around a local session, asked to run where no session exists. But there's a question none of it answers, and it's the one that matters most once more than one person can touch the project:

**Before this pipeline runs, can you tell me exactly what is about to change?**

---

## Railway is building an answer

To be completely fair: Railway is working on exactly this problem. `railway config` is their Infrastructure-as-Code system, and it's real:

```
plan   Preview the changes Railway would make from .railway/railway.ts
apply  Apply the changes from .railway/railway.ts to the linked Railway project
init   Create .railway/railway.ts for this repo or import from the linked project
pull   Import the linked Railway project's current configuration
```

That's a genuine reconciliation loop, declare your desired state in `.railway/railway.ts`, preview the delta with `plan`, converge with `apply`. It can define services, databases, volumes, buckets, domains, variables and replicas, and it has a detailed exit code for gating CI on drift.

It is also, by Railway's own labelling, **experimental**. Their [Infrastructure as Code documentation](https://docs.railway.com/infrastructure-as-code) states it plainly in the limitations section: _"Infrastructure as Code is experimental."_ TypeScript is currently the only supported language, with others possibly to follow.

That's not a knock — it's a feature under active development, honestly labelled, and it's worth watching. If you want to explore it, start with [Railway's IaC docs](https://docs.railway.com/infrastructure-as-code) and the [reference](https://docs.railway.com/infrastructure-as-code/reference).

What it does tell you is what you're adopting today: a TypeScript file, a Node toolchain, an npm dependency inside your repo, and a preview-track feature.

railctl makes a different set of bets: YAML, a single static binary with no runtime, and a stable release line.

---

## Enter railctl

The bet is the same one Kubernetes made a decade ago: **stop describing your infrastructure through actions, and start describing it as a document.**

Not "create a service, then set a variable, then attach a volume." Instead: here is what the system should look like, and go make that true.

> Your infrastructure should be a file you can review in a pull request.

That's the whole idea. Everything below is mechanics.

### The loop

Three commands. Here's the [n8n queue-mode example](https://github.com/kubenoops/railctl/tree/main/examples/n8n) from the repo, Postgres, Redis, an n8n web primary and two workers, in one file:

```bash
railctl diff  -f stack.yaml          # nothing exists yet — here's what I'd create
railctl apply -f stack.yaml --await  # reconcile, wait for SUCCESS
railctl diff  -f stack.yaml          # clean — live matches the file
```

That third command prints:

```
No changes. Railway state matches the config.
```

Which is reassuring. The interesting case is when it doesn't.

### Drift is the feature

Someone bumps the worker replica count in the dashboard during a traffic spike and
forgets to mention it. A week later:

```
Service: n8n-worker (update)
  ~ deploy.replicas: 2 → 4

0 to create, 1 to update, 0 to delete
```

Field-level. Old value, new value. Not "something changed" — _exactly_ what changed, in a form you can act on. Either you accept reality and update the manifest, or you run `apply` and put it back.

Secrets don't leak into that output. Any variable whose key looks sensitive is masked to a fixed 14 characters — the first two runes, then twelve asterisks — so the mask reveals neither the value's length nor its suffix:

```
  ~ variables.N8N_ENCRYPTION_KEY: a3************ → f7************
```

You can see _that_ it changed. You can't see what it is. That's what makes diff output safe to paste into a CI log or a PR comment.

Masking happens on the way to your terminal, not on the way in, railctl holds the real values internally, so `apply` writes the actual secret while `diff` only ever shows you the mask.

### Teardown is symmetric

```bash
railctl delete -f stack.yaml --yes
```

Deletes exactly what the manifest declares, services in reverse order, then their declared volumes, and nothing else. Live services not in your file are never touched. When you're evaluating a tool, knowing you can cleanly undo it matters as much as knowing it works.😉

---

## The architecture

railctl has 57 commands and is much smaller than that sounds, because every one of them is the same four steps:

![railctl architecture — authenticate, resolve, call, format](/images/posts/railctl-railway-kubectl-style/railctl-architecture.png)

1. **Authenticate.** Read a token from `--token` or `RAILWAY_TOKEN`. Detect its type: account, workspace, or project-scoped.
2. **Resolve.** Railway's API speaks UUIDs; humans speak names. Turn `-p myapp -e production` into UUIDs.
3. **Call.** One GraphQL request.
4. **Format.** Table, wide, JSON, or YAML depending on `-o`.

---

## Stateless, and two dependencies

Notice what's absent from that architecture: **any local state.** No `~/.config/railctl`, no `.railctlrc`, no linked-project file, no cache, no database. Every invocation starts from nothing and takes its entire context from flags and environment variables.

Nothing to link. Nothing to go stale. Nothing that differs between your laptop and a CI runner:

```
$ railctl get projects
❌ Error: no API token provided. Set RAILWAY_TOKEN environment variable or use --token flag
```

No "run link first." Just: give me a token, and the dependency list is two entries long:

- `spf13/cobra` — CLI scaffolding
- `gopkg.in/yaml.v3` — YAML parsing and output

Everything else is the Go standard library. No testify, no viper, no logging framework, no GraphQL client — the API layer is `net/http` and `encoding/json`,written by hand.

That's a deliberate constraint enforced in review, and it buys three things.
**Supply chain surface:** two things to audit, for a tool holding a token that can delete your production environment.
**Comprehensibility:** nobody can hide behind "the framework handles that."
**Portability:** a static binary, no runtime ; `curl`, `chmod +x`, done.

---

## Which is what makes CI work

![railctl gh action pipeline](/images/posts/railctl-railway-kubectl-style/railwaycicd.png)

Put those pieces together and the pipeline story falls out for free.

**No link step.** A project-scoped token carries its own project and environment, so the manifest needs no `-p`/`-e` flags and the runner needs no setup command.

**A token that can't overreach.** Project-scoped tokens are bounded to one project and environment. A pipeline holding one cannot touch another project — not by misconfiguration, not by a typo'd flag. That's least privilege enforced by the credential, not by convention.

**No interactive prompts, ever.** A missing parameter is an error and an exit, not a question. There is no code path that can block waiting for stdin.

**Color when you ask for it.** `--color` forces ANSI even when stdout isn't a terminal, so diffs stay readable in CI logs.

Which makes the useful pattern short — diff on a pull request, apply on merge.

---

## What we deliberately did not build

A feature list tells you what a tool does. The **no** list tells you whether the people building it have judgment.

**No config files.** No `.railctlrc`, no `~/.config/railctl/config.yaml`. Config files create hidden state, and hidden state makes behavior impossible to reproduce. Flags and environment variables are explicit and composable.

**No `context.Context` threading.** Commands are short-lived and sequential, and the HTTP client has a 60-second timeout. Threading context through every signature would be ceremony without a use case. If cancellation becomes a real need, we'll add it then.

**No interactive prompts.** Covered above, but it's a design rule, not a side effect: prompts are hostile to automation.

**No structured logging.** Debug output is `fmt.Fprintf(os.Stderr, ...)`. No levels, no JSON envelope — it exists for a human reading stderr during troubleshooting, not for an aggregator.

Each is a place we could have added something and chose not to. The constraint _is_ the design.

---

## Where this leaves you

Railway is a genuinely excellent platform, and its CLI is a capable tool. If you're deploying from your laptop, `railway up` is probably all you need, and their IaC work is worth watching as it matures.

railctl is for the other half of the lifecycle: when several people can change the same project, when a pipeline needs to know what changed before it changes it, and when "why is it configured like this?" needs an answer better than nobody remembers.

```bash
curl -Lo railctl https://github.com/kubenoops/railctl/releases/latest/download/railctl-linux-amd64
chmod +x railctl && sudo mv railctl /usr/local/bin/
export RAILWAY_TOKEN=your-token-here
```

Then point it at something real — the [n8n example](https://github.com/kubenoops/railctl/tree/main/examples/n8n) is four services in one manifest, verified against live Railway by CI, so it works as written.

Your infrastructure should be a file you can review in a pull request. Now it can be.

## References

<div class="ref-wrap">
  <a class="ref-item" href="https://github.com/kubenoops/railctl" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/github.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">railctl</div>
      <div class="ref-desc">The tool itself — source, releases, and the n8n example stack.</div>
    </div>
  </a>
  <a class="ref-item" href="https://railway.app" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/railway.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">Railway</div>
      <div class="ref-desc">The deployment platform railctl drives.</div>
    </div>
  </a>
  <a class="ref-item" href="https://docs.railway.com/cli" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/railway.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">Railway CLI docs</div>
      <div class="ref-desc">Official reference for the CLI compared throughout this post.</div>
    </div>
  <a class="ref-item" href="https://kubernetes.io/docs/reference/kubectl/" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/kubernetes.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">kubectl</div>
      <div class="ref-desc">The interface railctl borrows its verbs and shapes from.</div>
    </div>
  </a>
</div>
