---
title: "Deploying n8n on Railway: the hard way, then the right way"
date: 2026-08-06 10:00:00
categories:
  - Blogs
tags:
  - railway
  - railctl
  - n8n
  - infrastructure-as-code
  - devops
banner: /images/posts/deploy-n8n-on-railway/n8nonrailway.png
cover: /images/posts/deploy-n8n-on-railway/n8nonrailway.png
description: "Four services, fifteen commands, forty minutes — and no record of what you did. Then the same stack as one file you can diff, review, and reproduce."
---

> Part two of the railctl series, this time we actually deploy something: n8n, in queue mode, on Railway.

Building an n8n queue-mode stack by hand works. Doing it twice, identically, does not.

![Deploying n8n on Railway](/images/posts/deploy-n8n-on-railway/n8nonrailway.png)
## Where we left off

In the [previous post](/siki-mahou/2026/08/05/railctl-railway-kubectl-style/) we looked at **what railctl is and what it's for**: a kubectl-shaped CLI for Railway, built on the idea that your infrastructure should be a document you can review in a pull request rather than a sequence of commands somebody once ran.

That post was mostly argument. This one is mostly typing. 🤔💭

Time to get our hands dirty.👩🏻‍💻

## The lab

> Visit : [Deploy-n8n-stack-on-railway-using-railctl](https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl)

Here's what we're going to build, and why it's a fair test rather than a toy demo.

**The workload:** [n8n](https://n8n.io), the workflow automation tool — running in **queue mode**. That's the production shape, where the web editor and the workflow execution run as separate services so a long-running workflow can't freeze your UI.

**Why this one?** Because it's genuinely awkward. It isn't a single container you point at a port. It's **four services** that have to know about each other:

- a **database** that needs a persistent volume, or you lose everything on redeploy
- a **queue** the workers pull jobs from
- a **primary** that needs a public URL
- **workers** that must share the primary's encryption key or they can't decrypt saved credentials

That's exactly the class of setup that's easy to build once by clicking around, and miserable to reproduce.

**The plan:** build it twice. First by hand, one command per thing (imperative way), then the identical stack as a single file (declaraative way). Same result both times; the difference is what you're left holding afterwards.

> **What you'll need:** a Railway account, `railctl` installed, and about twenty minutes. Everything else is below.

## "It's just one service, right?"

That's the thing — it looks like one. You open the Railway dashboard and start clicking. Ten minutes, tops.

Then you hit the wiring. Each service needs the others' hostnames, ports and passwords. Postgres needs its volume mounted at exactly the right path. The workers need the primary's encryption key, byte for byte.

Forty minutes later it's running, and you're not entirely sure what you did.

<!-- more -->

That last part is the problem this post is really about.

---

## What we're building

![n8n queue-mode architecture on Railway](/images/posts/deploy-n8n-on-railway/diagramn8n.png)

| Service        | Image                                          | Purpose                         |
| -------------- | ---------------------------------------------- | ------------------------------- |
| `n8n-postgres` | `ghcr.io/railwayapp-templates/postgres-ssl:16` | Workflow & credential storage   |
| `n8n-redis`    | `redis:7-alpine`                               | Bull job queue                  |
| `n8n-primary`  | `n8nio/n8n:latest`                             | Web editor, API, webhooks       |
| `n8n-worker`   | `n8nio/n8n:latest`                             | Workflow execution (2 replicas) |

Only `n8n-primary` gets a public URL. Postgres and Redis are reachable only over Railway's private network, at `*.railway.internal` — they have no public networking at all.

---

## Prerequisites

**railctl**, install the binary:

```bash
curl -Lo railctl https://github.com/kubenoops/railctl/releases/latest/download/railctl-linux-amd64
chmod +x railctl && sudo mv railctl /usr/local/bin/
```

Or build from source:

```bash
git clone https://github.com/kubenoops/railctl.git
cd railctl
make build
sudo mv railctl /usr/local/bin/
```

You'll also need **a Railway API token** from [railway.app/account/tokens](https://railway.app/account/tokens), and **three generated secrets**:

```bash
openssl rand -hex 16   # run three times
```

Set up your shell from the example file:

```bash
# .envrc.example
# Railway API token — get one from https://railway.app/account/tokens
export RAILWAY_TOKEN="acc-token, workspace-token, project-token"

# Target project and environment (created automatically if they don't exist)
export RAILCTL_PROJECT="my-n8n"
export RAILCTL_ENVIRONMENT="production"

# n8n secrets — generate with: openssl rand -hex 16
export N8N_POSTGRES_PASSWORD=""
export N8N_REDIS_PASSWORD=""
export N8N_ENCRYPTION_KEY=""
```

```bash
cp .envrc.example .envrc     # then fill in the token and the three secrets
source .envrc
```

> Add `.envrc` to `.gitignore` — it holds your token and three real secrets. Only `.envrc.example` gets committed.

### A note on tokens

We're starting with a **workspace token**, and we have to: creating a project requires workspace-wide access. A project-scoped token is bound to a project that already exists.

`railctl` points this out as you go:

```
hint: this project-scoped operation is using a broad account/workspace token.
A project token (see 'railctl token create') grants least privilege — it is
leaf-bound to one project+environment. Silence with RAILCTL_NO_HINTS=1.
```

Once the project exists, you can mint a token scoped to exactly it:

```bash
railctl token create n8n-demo -p my-n8n -e production
```

The raw token prints **once**, store it immediately, swap it into `.envrc`, and `source` again. If it leaks, it exposes one project and one environment instead of your whole workspace. For production and CI, that's the right move.

> For this walkthrough we'll stay on the workspace token, one less moving part while we're demonstrating everything else.

### How railctl knows where things go

The commands below never say which project to use, because `.envrc` exports it:

```bash
export RAILCTL_PROJECT="my-n8n"
export RAILCTL_ENVIRONMENT="production"
```

railctl resolves context as **flag → environment variable → error**. It never guesses. Prefer not to export? Pass the flags instead, every command here works either way:

```bash
railctl create service n8n-postgres --image redis:7-alpine -p my-n8n -e production
```

> Secrets are the exception: `$env(...)` references in the manifest are read from your environment at apply time, so those must be exported regardless.

---

## Part one: the hard way

We'll build all four services imperatively, one command per thing. This is already nicer than clicking through a dashboard, and it's worth noticing _why_ it still isn't enough.

### Create the project and environment

```bash
railctl create project my-n8n

  Created project "my-n8n" (ID: ************* )
  Default environments:
    - production
```

Let's list the projects:

```bash
railctl get projects

NAME               SERVICES  UPDATED
my-n8n             0         14m ago
test-railctl-blog  0         50m ago
```

> ⚠️ The commands below are abbreviated. Each service needs roughly fifteen environment variables; printing them all here would bury the point. What follows shows the shape, enough to understand what's happening, not enough to run a working stack.  For the complete configuration, see [Deploy n8n with railctl](https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl/tree/main/n8n/configs) one file per service, with every variable. If you're following along and want n8n actually running at the end of Part One, use those values rather than the excerpts below. 


### Postgres — service, volume, variables

Three separate commands, and the order matters: the service must exist before it can have a volume or variables.

1. Create postgress service:

```bash
railctl create service n8n-postgres \
  --image ghcr.io/railwayapp-templates/postgres-ssl:16 \
  --start-command "/bin/sh -c 'unset PGPORT; docker-entrypoint.sh postgres --port=5432'" \
  --restart-policy ON_FAILURE --max-retries 10

Service 'n8n-postgres' created with image 'ghcr.io/railwayapp-templates/postgres-ssl:16' (ID: ************* )
Deploy configuration applied to environment 'production'
```
2. Create the volume for postgres service

```bash
railctl create volume --mount-path /var/lib/postgresql/data -s n8n-postgres

Volume 'n8n-postgres-volume' created and attached to service 'n8n-postgres' at '/var/lib/postgresql/data'
Volume ID: *************
```
3. Set needed variables for the postgres service

```bash
railctl set variable \
  POSTGRES_USER=postgres \
  "POSTGRES_PASSWORD=$N8N_POSTGRES_PASSWORD" \
  POSTGRES_DB=n8n \
  PGPORT=5432 \
  PGDATA=/var/lib/postgresql/data/pgdata \
  -s n8n-postgres

5 variables set successfully for service 'n8n-postgres' in environment 'production'
(Deployment triggered)
```

> The full config also sets `PGUSER`, `PGPASSWORD`, `PGDATABASE`, `PGHOST` and `DATABASE_URL` as service references. See [`/n8n/configs/01-n8n-postgres.yaml`](https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl/tree/main/n8n/configs/01-n8n-postgres.yaml).

> Notice the password went in as a shell variable — which means it's now in your shell history, and in the scrollback of whoever's watching.

### Redis

1. Create redis service:

```bash
railctl create service n8n-redis --image redis:7-alpine \
  --restart-policy ON_FAILURE --max-retries 10
```

2. Create and mount the volume for redis service

```bash
railctl create volume --mount-path /data -s n8n-redis
```

3. Set needed variables for redis
```bash
railctl set variable \
  "REDIS_PASSWORD=$N8N_REDIS_PASSWORD" \
  REDISPORT=6379 REDISUSER=default \
  -s n8n-redis
```

### The n8n primary

This one needs a public domain, and a dozen variables wiring it to both Postgres and Redis.

1. Create n8n-primary service, exposing it with public url:

```bash
railctl create service n8n-primary --image n8nio/n8n:latest \
  --start-command "n8n start" \
  --restart-policy ON_FAILURE --max-retries 10 \
  --generate-domain 5678
```

2. Set needed variables for n8n-primary service:

```bash
railctl set variable \
  DB_TYPE=postgresdb \
  'DB_POSTGRESDB_HOST=${{n8n-postgres.PGHOST}}' \
  'DB_POSTGRESDB_PASSWORD=${{n8n-postgres.POSTGRES_PASSWORD}}' \
  EXECUTIONS_MODE=queue \
  "N8N_ENCRYPTION_KEY=$N8N_ENCRYPTION_KEY" \
  PORT=5678 \
  -s n8n-primary
```

> Abbreviated — the full set is in  [`n8n/configs/03-n8n-primary.yaml`](https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl/tree/main/n8n/configs/03-n8n-primary.yaml).

### The workers

Same image as the primary, different start command, two replicas, and they must share the primary's encryption key.

1. Create the n8n-worker service:

```bash
railctl create service n8n-worker --image n8nio/n8n:latest \
  --start-command "n8n worker" \
  --restart-policy ON_FAILURE --max-retries 10 \
  --replicas 2
```
2. Set needed variables for n8n-worker service:

```bash
railctl set variable \
  EXECUTIONS_MODE=queue \
  "N8N_ENCRYPTION_KEY=$N8N_ENCRYPTION_KEY" \
  'QUEUE_BULL_REDIS_HOST=${{n8n-redis.REDISHOST}}' \
  -s n8n-worker
```

### It works

Let's verify that the created services are up :

1. Get services
```bash
railctl get services

NAME          SOURCE                                       STATUS   UPDATED
n8n-redis     redis:7-alpine                               SUCCESS  8m ago
n8n-primary   n8nio/n8n:latest                             SUCCESS  4m ago
n8n-worker    n8nio/n8n:latest                             SUCCESS  2m ago
n8n-postgres  ghcr.io/railwayapp-templates/postgres-ssl:16  SUCCESS  16m ago
```
2. Get variables of n8n-primary
```bash
railctl get variables -s n8n-primary

KEY                             VALUE
---                             -----
DB_POSTGRESDB_HOST
DB_POSTGRESDB_PASSWORD          fb************
DB_TYPE                         postgresdb
EXECUTIONS_MODE                 queue
N8N_ENCRYPTION_KEY              01************
PORT                            5678
RAILWAY_ENVIRONMENT             production
RAILWAY_PRIVATE_DOMAIN          n8************
RAILWAY_PROJECT_NAME            my-n8n
RAILWAY_PUBLIC_DOMAIN           n8n-primary-production-c0e9.up.railway.app
RAILWAY_SERVICE_NAME            n8n-primary

Total: 17 variable(s)

  (Sensitive values masked. Use --show-values to reveal)
```

Four services, running. Roughly fifteen commands to get here, in an order that mattered, with three secrets typed into a terminal.

Now answer this: **could you reproduce this exactly, in a staging environment, tomorrow?**

Not approximately. Exactly; same variables, same replica counts, same restart policies, same mount paths. From what? There's no record of what you just did. The dashboard shows you the _result_, never the recipe.

That's the gap. Not that the commands are hard, they worked fine, but that running them left nothing behind.

---

## Part two: the same thing, as a file

Here is that entire stack as one document. We'll go through it a service at a time, because each one demonstrates something different.

### Postgres: volumes and privacy

```yaml
services:
  - name: n8n-postgres
    image: ghcr.io/railwayapp-templates/postgres-ssl:16
    deploy:
      startCommand: "/bin/sh -c 'unset PGPORT; docker-entrypoint.sh postgres --port=5432'"
      restartPolicy: ON_FAILURE
      maxRetries: 10
    # No public networking: clients reach it at n8n-postgres.railway.internal
    volume:
      mountPath: /var/lib/postgresql/data
      backupSchedules: [daily]
    variables:
      POSTGRES_USER: "postgres"
      POSTGRES_PASSWORD: "$env(N8N_POSTGRES_PASSWORD)"
      POSTGRES_DB: "n8n"
```

Two things the imperative version couldn't express as cleanly. The **volume is part of the service definition**, not a second command you must remember. And `backupSchedules: [daily]` declares a backup policy — state, not an action.

The password is `$env(N8N_POSTGRES_PASSWORD)`, a _reference_. The file names the secret; your environment supplies the value at apply time. **This file is safe to commit.**

### The primary: public networking and references

```yaml
- name: n8n-primary
  image: n8nio/n8n:latest
  deploy:
    startCommand: "n8n start"
  networking:
    domain:
      port: 5678
  variables:
    DB_POSTGRESDB_HOST: "${{n8n-postgres.PGHOST}}"
    DB_POSTGRESDB_PASSWORD: "${{n8n-postgres.POSTGRES_PASSWORD}}"
    EXECUTIONS_MODE: "queue"
    N8N_ENCRYPTION_KEY: "$env(N8N_ENCRYPTION_KEY)"
```

`${{n8n-postgres.POSTGRES_PASSWORD}}` is a **service reference** resolved by Railway at runtime. The password is never copied between services; it lives in one place and everything else points at it.

### The workers: replicas

```yaml
- name: n8n-worker
  image: n8nio/n8n:latest
  deploy:
    startCommand: "n8n worker"
    replicas: 2
  variables:
    N8N_ENCRYPTION_KEY: "$env(N8N_ENCRYPTION_KEY)"
```

Same image, different command, `replicas: 2`. The scaling decision is a line in a file, reviewable like any other change.

### The reveal

You built that stack by hand. Now point railctl at the manifest and ask what it would change:

```bash
railctl diff -f /n8n/stack.yaml

No changes. Railway state matches the config.
```

Nothing to do. The file already describes what you spent forty minutes building.

Which means from here on, the file is the source of truth, and the fifteen commands were just a slow way of typing it.

---

## Deploying from scratch

Prove it. Tear the whole thing down and rebuild from the manifest alone:

```bash
railctl delete -f /n8n/stack.yaml --yes

The following will be deleted from project 'my-n8n' environment 'production':
  - service 'n8n-worker'
  - service 'n8n-primary'
  - service 'n8n-redis'
  - service 'n8n-postgres'
  - volume 'n8n-redis-volume' (mounted at /data, declared by 'n8n-redis')
  - volume 'n8n-postgres-volume' (mounted at /var/lib/postgresql/data, declared by 'n8n-postgres')
Delete 4 service(s) and 2 volume(s)? This cannot be undone. [y/N]: y
Deleting service 'n8n-worker'...
✓ Service 'n8n-worker' deleted
Deleting service 'n8n-primary'...
✓ Service 'n8n-primary' deleted
Deleting service 'n8n-redis'...
✓ Service 'n8n-redis' deleted
Deleting service 'n8n-postgres'...
✓ Service 'n8n-postgres' deleted
Deleting volume 'n8n-redis-volume'...
✓ Volume 'n8n-redis-volume' deleted
Deleting volume 'n8n-postgres-volume'...
✓ Volume 'n8n-postgres-volume' deleted

4 services deleted, 2 volumes deleted, 0 skipped (not found)
```

Now everything is a create:

```bash
railctl diff -f /n8n/stack.yaml

Service: n8n-postgres (create)
  + image: ghcr.io/railwayapp-templates/postgres-ssl:16
  + deploy.startCommand: /bin/sh -c 'unset PGPORT; docker-entrypoint.sh postgres --port=5432'
  + deploy.restartPolicy: ON_FAILURE
  + deploy.maxRetries: 10
  ...
Service: n8n-redis (create)
  + image: redis:7-alpine
  + deploy.restartPolicy: ON_FAILURE
  + deploy.maxRetries: 10
  ...
Service: n8n-primary (create)
  + image: n8nio/n8n:latest
  + deploy.startCommand: n8n start
  ...
Service: n8n-worker (create)
  + image: n8nio/n8n:latest
  + deploy.startCommand: n8n worker
  + deploy.replicas: 2
  ...

4 to create, 0 to update, 0 to delete
```

> Output trimmed for length, you'll see the full thing in your terminal !

Now let s apply evrything from one file manifest
```bash
railctl apply -f /n8n/stack.yaml --await
```
See everything up on railway dashboard:
![n8n-stack up](/images/posts/deploy-n8n-on-railway/n8n-onrailway.png)
```bash
railctl diff -f /n8n/stack.yaml     
0 to create, 0 to update, 0 to delete
```

There are no gaps between the source of truth, `stack.yaml` file, and the running services on Railway.
Fifteen commands became three. More importantly: the result is _identical_ every time, because it's derived from a file rather than from memory.

---

## Day two: changing something

Traffic is up and two workers aren't keeping pace. Edit one line:

```diff
   - name: n8n-worker
     deploy:
-      replicas: 2
+      replicas: 3
```

Then run the same two commands as the initial deploy:

```bash
railctl diff  -f /n8n/stack.yaml
railctl apply -f  /n8n/stack.yaml
```

There's no separate "update" path to learn, you change the description of the system, and the system is reconciled to match.

And the change went through a file, which means it can go through a pull request.

---

## The part that actually matters: drift

Here's the scenario every team hits.

It's a busy afternoon. Someone opens the Railway dashboard and bumps the worker replicas to handle a spike. It works, the spike passes, and they never mention it.

Your manifest says 3. Reality says something else. Nobody knows.

```bash
Service: n8n-worker (update)
  ~ deploy.replicas: 3 → 5

0 to create, 1 to update, 0 to delete
```

Field-level. Old value, new value. Not "something changed", _exactly_ what changed, and where.

From here you have two honest choices, and railctl doesn't pick for you:

- **The change was right** : update the manifest to say 5. Reality informs the file, and the next reviewer sees why.
- **The change was accidental** : run `apply`, and the file wins.

Either way, the drift got _noticed_. That's the thing you cannot get from a dashboard, and it's the whole reason to keep a manifest at all.

---

## Secrets stay secret

`diff` prints what changed, which raises an obvious question about the three secrets in this stack.

```
  ~ variables.N8N_ENCRYPTION_KEY: a3************ → f7************
```

Any variable whose name looks sensitive is masked to a fixed width; first two characters, then twelve asterisks, so the mask reveals neither the value's length nor its ending.

You can see _that_ it changed. You can't see what it is. Which is what makes this output safe to paste into a CI log or a pull request comment.

---

## Putting it in CI

Everything so far ran from a laptop. The payoff is that none of it has to.

Because `railctl` keeps no local state, no linked project, no config file, nothing to initialise, a pipeline needs exactly two things: the binary and a token. And because a **project-scoped token** carries its own project and environment, the manifest needs no `-p`/`-e` flags, and the token physically cannot reach any other project.

Up to now we've used a workspace token, because creating a project needs one. CI doesn't. This pipeline only ever reconciles one project's manifest, so give it a token that can do exactly that and nothing else:

```bash
railctl token create ci -p my-n8n -e production
```

The pattern that follows: **preview on pull requests, reconcile on merge.**

```yaml
name: infra

on:
  pull_request:
    paths:
      - "n8n/stack.yaml"
      - ".github/workflows/infra.yml"
  push:
    branches: [main]
    paths:
      - "n8n/stack.yaml"
      - ".github/workflows/infra.yml"

permissions:
  contents: read

jobs:
  reconcile:
    runs-on: ubuntu-latest
    env:
      RAILWAY_TOKEN: ${{ secrets.RAILWAY_PROJECT_TOKEN }}
      N8N_POSTGRES_PASSWORD: ${{ secrets.N8N_POSTGRES_PASSWORD }}
      N8N_REDIS_PASSWORD: ${{ secrets.N8N_REDIS_PASSWORD }}
      N8N_ENCRYPTION_KEY: ${{ secrets.N8N_ENCRYPTION_KEY }}
    steps:
      - uses: actions/checkout@v4

      - name: Install railctl
        run: |
          curl -Lo railctl https://github.com/kubenoops/railctl/releases/latest/download/railctl-linux-amd64
          chmod +x railctl && sudo mv railctl /usr/local/bin/

      - name: Preview changes
        run: railctl diff -f n8n/stack.yaml --color

      - name: Apply
        if: github.ref == 'refs/heads/main'
        run: railctl apply -f n8n/stack.yaml --await
```

Now a change to the stack is a pull request. The diff runs automatically and posts what would change; a reviewer approves the _infrastructure change_ the same way they'd approve a code change; merging applies it.

`--color` forces ANSI output even though CI isn't a terminal, so the diff stays readable in the log.

We scale up the n8n-worker instance to 3 workers `replicas = 3` and here are the results:

1. Github workflow output :
![n8n-reconcile wf](/images/posts/deploy-n8n-on-railway/n8n-reconcile-wf.png)

2. Railway dashboard:
![railway](/images/posts/deploy-n8n-on-railway/day2-op.png)

---

## Tearing it down

```bash
railctl delete -f /n8n/stack.yaml --yes
```

Services are deleted in reverse manifest order, then their declared volumes, because deleting a service orphans its volume, so `railctl` removes them explicitly. Anything live that _isn't_ in your file is left alone.

Nothing orphaned, nothing quietly billing you.

---

## What changed between part one and part two

The infrastructure is identical. What changed is where it lives.

In part one it lived in Railway, and in the memory of whoever ran the commands. In part two it lives in a file — one you can diff, review, roll back, and hand to someone else.

Fifteen commands became three, but the real difference isn't the count. It's that the second version can answer the question the first one couldn't: _what is running right now, and is it what we intended?_

```bash
curl -Lo railctl https://github.com/kubenoops/railctl/releases/latest/download/railctl-linux-amd64
chmod +x railctl && sudo mv railctl /usr/local/bin/
```

The full stack used here lives in [`Deploy-n8n-stack-on-railway-using-railctl/n8n/`](https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl/tree/main/n8n) — manifest, per-service configs, and scripts.

---

## References

<div class="ref-wrap">
  <a class="ref-item" href="https://github.com/kubenoops/railctl" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/github.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">railctl</div>
      <div class="ref-desc">The tool used throughout — source, releases, and docs.</div>
    </div>
  </a>
  <a class="ref-item" href="https://github.com/kubenoops/railctl/tree/main/examples/n8n" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/github.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">n8n queue-mode example</div>
      <div class="ref-desc">The complete stack.yaml and per-service configs from this post.</div>
    </div>
  </a>
  <a class="ref-item" href="https://n8n.io" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/n8n.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">n8n</div>
      <div class="ref-desc">The workflow automation tool we're deploying.</div>
    </div>
  </a>
  <a class="ref-item" href="https://docs.n8n.io/hosting/scaling/queue-mode/" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/n8n.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">n8n queue mode</div>
      <div class="ref-desc">Official docs for the primary/worker split this stack uses.</div>
    </div>
  </a>
  <a class="ref-item" href="https://railway.app" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/railway.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">Railway</div>
      <div class="ref-desc">The platform hosting all four services.</div>
    </div>
  </a>
  <a class="ref-item" href="https://github.com/0XSIKIPON/Deploy-n8n-stack-on-railway-using-railctl" target="_blank" rel="noopener noreferrer">
    <div class="ref-icon"><img class="no-lightbox" src="/siki-mahou/images/refs/github.svg" alt="" loading="lazy"></div>
    <div class="ref-info">
      <div class="ref-name">Deploy n8n stack with railctl</div>
      <div class="ref-desc">Get your lab template and start deploying your n8n to railway</div>
    </div>
  </a>
</div>
