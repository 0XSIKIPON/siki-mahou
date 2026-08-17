---
title: "Arab Security Cyber Wargames 2023 Quals — Crypto Writeups"
date: 2024-04-11 12:00:00
categories:
  - CTF writeups
tags:
  - ctf
  - crypto
  - elgamal
  - pohlig-hellman
  - discrete-log
banner: /images/posts/ascwg-2023-quals-crypto/awgamquals.jpeg
cover: /images/posts/ascwg-2023-quals-crypto/awgamquals.jpeg
description: "Three crypto challenges from the ASCWG 2023 qualifiers — a nonlinear system that was linear in disguise, and two ElGamal breaks that both come down to a smooth prime."
---

A "nonlinear" system that was linear all along, and two ElGamal challenges undone by the same weak prime.

![Arab Security Cyber Wargames](/siki-mahou/images/posts/ascwg-2023-quals-crypto/awgamquals.jpeg)

## Event details

|                   |                                                           |
| ----------------- | --------------------------------------------------------- |
| **Dates**         | Fri, 04 Aug 2023, 13:00 UTC — Sat, 05 Aug 2023, 13:00 UTC |
| **Location**      | On-line                                                   |
| **Format**        | Jeopardy                                                  |
| **Organizers**    | [Arab Security Cyber Wargames](https://ctftime.org/event/2046/)                              |
| **Future weight** | 20.00                                                     |
| **Rating weight** | 20.00                                                     |

## About the CTF

The **Arab Security Cyber Wargames (ASCWG)** is a regional cybersecurity competition for teams from across the Arab world, run in a qualifiers-then-finals format. The qualifier round is jeopardy-style with the usual categories; `web`, `crypto`, `pwn`, etc...

This writeup covers the three crypto challenges from the 2023 qualifiers:

| #   | Challenge            | Weakness                                          | Tooling                     |
| --- | -------------------- | ------------------------------------------------- | --------------------------- |
| 1   | `perfect-encryption` | Multiplicative masking that inverts algebraically | Linear algebra (or Gröbner) |
| 2   | `power-times`        | ElGamal over a field with smooth $q-1$            | Pohlig–Hellman              |
| 3   | `sign-hell`          | ElGamal signatures over a prime with smooth $p-1$ | Pohlig–Hellman              |


<!-- more -->

---

##  perfect-encryption

> Desc : I missed up with my perfect system. Can you figure out what I did wrong?.

### Source

```python
from Crypto.Util.number import bytes_to_long, getStrongPrime
from random import getrandbits

FLAG = bytes_to_long(b"ASCWG{XXXX}")

p = getStrongPrime(512)
a, b, c = getrandbits(256), getrandbits(256), getrandbits(256)

x = getrandbits(512)
y = FLAG * x % p

f1 = (a*x*y + b*x - c*y + a*b) % p
f2 = (a*x*y - a*b*x + c*y - a*b*c) % p
f3 = (a*x*y + a*b*x - b*y + a*c) % p

print(f"{a=}\n{b=}\n{c=}\n{p=}")
print(f"{f1=}\n{f2=}\n{f3=}")
```

Given data:

```python
a = 104290256438464238265920655110843789355215462446618909362719610248661044655027
b = 51377041544373038040355907810892111390501284088151402869947729149784382975340
c = 33607469487038655534452887169909251709064921357237953655926459853107316549445
p = 11777932795008234937554901192530674345218991539703072132156127068946946972145785796843203243414854874792790874422630471893317874927684942543648149902518429
f1 = 4393450432502936586942125381637603594967424429450041652241154373587594289593710667561969065441313205238350018007250796310103876164723965465384784041009952
f2 = 11758359456591126288355398100033811157654788859704663069490658186848940636735180110386914705819056992670969028976783609655478685964439506912465882470156531
f3 = 4526962740230169131710354844377916940967201676526826430849484531211915498483780757376719893812797798719451042286927996929324321141661155944161904629619229
```

### Analysis

The flag is hidden by a **multiplicative mask**: $y = \text{FLAG}\cdot x \bmod p$ with $x$ random. That part is fine on its own — one equation, two unknowns, no information. But the challenge then publishes three functions of $x$ and $y$ with **all coefficients $a, b, c$ known**.

The flag falls out of the ratio, so we never need $x$ and $y$ individually, only their quotient:

$$\text{FLAG} = y\thinspace x^{-1} \bmod p$$

### The key observation; the system is linear

Look at which products of unknowns actually appear:

$$
\begin{aligned}
f_1 &= a\thinspace (xy) + b\thinspace x - c\thinspace y + ab\\
f_2 &= a\thinspace (xy) - ab\thinspace x + c\thinspace y - abc\\
f_3 &= a\thinspace (xy) + ab\thinspace x - b\thinspace y + ac
\end{aligned}
$$

Only three distinct monomials occur: $xy$, $x$, and $y$. Nothing squared, no $x^2y$, no higher powers. So substituting $z := xy$ and treating $(z, x, y)$ as **three independent unknowns** turns this into an ordinary $3\times3$ linear system over $\mathbb{F}_p$:

$$
\begin{pmatrix}
a & b & -c\\
a & -ab & c\\
a & ab & -b
\end{pmatrix}
\begin{pmatrix} z\\ x\\ y \end{pmatrix}
{=}
\begin{pmatrix} f_1 - ab\\ f_2 + abc\\ f_3 - ac \end{pmatrix}
$$

Three equations, three unknowns, all coefficients known. Gaussian elimination and you're done — the nonlinearity was never real, it was hidden by the change of variable.

The relation $z = xy$ is then a **free consistency check**: the linear solve never enforces it, so if the recovered values satisfy it, the solution is certainly correct.

### Exploit — linear solve

```python
from Crypto.Util.number import long_to_bytes

# unknowns ordered as (z, x, y) with z = x*y
M = [[a,  b,   -c],
     [a, -a*b,  c],
     [a,  a*b, -b]]
v = [(f1 - a*b) % p, (f2 + a*b*c) % p, (f3 - a*c) % p]

def solve3(M, v, p):
    """Gauss-Jordan on a 3x3 system over F_p."""
    M = [row[:] + [v[i]] for i, row in enumerate(M)]
    n = 3
    for i in range(n):
        piv = next(r for r in range(i, n) if M[r][i] % p)
        M[i], M[piv] = M[piv], M[i]
        inv = pow(M[i][i], -1, p)
        M[i] = [(e * inv) % p for e in M[i]]
        for r in range(n):
            if r != i and M[r][i] % p:
                f = M[r][i]
                M[r] = [(M[r][k] - f * M[i][k]) % p for k in range(n + 1)]
    return [M[i][n] for i in range(n)]

z, x, y = solve3(M, v, p)
assert (x * y - z) % p == 0, "z != x*y -- solution inconsistent"

flag = (y * pow(x, -1, p)) % p
print(long_to_bytes(flag))
```

Verified output:

```
consistency  x*y == z : True
b'ASCWG{4tt@ck_7h3_Id3@l_w0RlD_0f_Gr0e6N2r$$}'
```

### Alternative — Gröbner basis

The flag text points at the intended route: treat the three relations as polynomials in $\mathbb{Z}_p[x,y]$ and let a **Gröbner basis** reduce the ideal. For a zero-dimensional ideal the basis comes back in the shape $\{x - x_0,\ y - y_0\}$, handing you the values directly:

```python
from sage.all import *
from Crypto.Util.number import long_to_bytes

PR.<xx, yy> = PolynomialRing(Zmod(p), 2)
g1 = (a*xx*yy + b*xx - c*yy + a*b)     - f1
g2 = (a*xx*yy - a*b*xx + c*yy - a*b*c) - f2
g3 = (a*xx*yy + a*b*xx - b*yy + a*c)   - f3

_x, _y = Ideal([g1, g2, g3]).groebner_basis()
__x = int(xx - _x)
__y = int(yy - _y)

flag = (__y * pow(__x, -1, p)) % p
print(long_to_bytes(int(flag)))
```

Both work. Gröbner is the general tool and needs no insight into the structure; the linear solve is faster and needs no Sage, but only because the system happened to have no genuine nonlinearity. Worth knowing both — spotting that a "nonlinear" system is linear in disguise is a recurring trick.

### Flag

```
ASCWG{4tt@ck_7h3_Id3@l_w0RlD_0f_Gr0e6N2r$$}
```

The pun is deliberate: an **ideal** in the ring-theory sense, and **Gröbner** bases as the tool for reducing one.

---

##  power-times

> Desc : The only way to survive is you have to be patient. `nc 34.154.18.2 6952`


### Source

```python
import os
from sage.all import *
FLAG = os.getenv("FLAG", "ASCWG{XXXX}").encode()

def gen_prime():
    while True:
        p = 2
        for _ in range((2<<2)+1):     # 9 iterations
            p *= getrandbits(58)
        if is_prime(p+1):
            return p+1

def encrypt():
    x = G(getrandbits(256))
    h = g^x
    y = G.random_element()
    s = h^y
    c1 = g^y
    m = G(int.from_bytes(FLAG, byteorder="big"))
    c2 = m*s
    return (q, g, h, c1, c2), x

if __name__ == "__main__":
    q = gen_prime()
    G = GF(q, modulus="primitive")
    g = G.gen()
    print(encrypt()[0])
```

Given data:

```python
enc_data = (178915177032804021050427140032746696723749962881188044861646798847736530826378026481351281365784523904963212130630320702637511158945976194698592786688001,
            47,
            23506596782805348271473410822447290141035450768469664403092777760012826524902520752525591669751760640593267778773839355953068054569089786842116869598655,
            109668851237469194500647406387083378710462885435536771582359767006353410353285009725972855520570415028994429516732733974365090983584555495335656061464216,
            64346280149354374601987893536846884687005438855607551246890647114769075770951969650738549609214399200239510984054091390476073753168405180421905540833220)
q, g, h, c1, c2 = enc_data
```

### Analysis

This is textbook **ElGamal**: private key $x$, public $h = g^x$, and a ciphertext

$$c_1 = g^y, \qquad c_2 = m\cdot h^y$$

Decryption normally needs $x$ to compute $s = c_1^{\thinspace x}$. Breaking it means recovering $x$ (or $y$) from a discrete log, which is hard in a well-chosen group.

The whole challenge is in `gen_prime`:

```python
p = 2
for _ in range(9):
    p *= getrandbits(58)
if is_prime(p+1):
    return p+1
```

The prime is built as **(a product of nine ~58-bit random numbers) + 1**. So $q - 1$ factors into pieces of at most 58 bits, and in practice much smaller, since random 58-bit integers are themselves composite and split further. That is a **smooth** group order.

⚠️ Note the group is $\mathbb{F}_q^*$ of order $q-1$, so smoothness of $q-1$ is exactly what matters here.

### Pohlig–Hellman

When the group order factors as $\prod p_i^{r_i}$ with every $p_i$ small, a discrete log in the full group reduces to:

1. one discrete log in each subgroup of order $p_i^{r_i}$ — each cheap, since the search space is $p_i$ rather than $q$;
2. recombining the residues with the **CRT**.

Note we solve for $y$ from $c_1 = g^y$ rather than for $x$ from $h = g^x$; either works, since $s = h^y = c_1^{\thinspace x}$ can be reconstructed from whichever exponent you get. Then

$$m = c_2\cdot s^{-1} \bmod q$$

### Exploit

```python
from sympy.ntheory.residue_ntheory import n_order, _discrete_log_pohlig_hellman
from sympy.ntheory.factor_ import factorint
from sympy.ntheory.modular import crt
from Crypto.Util.number import long_to_bytes

def dlog(n, a, b, factors):
    """discrete log of a base b mod n, given the factorisation of the order"""
    f = factors
    l = [0] * len(f)
    a %= n
    b %= n
    order = n_order(b, n)

    for i, (pi, ri) in enumerate(f.items()):
        for j in range(ri):                       # lift prime-power exponents digit by digit
            gj = pow(b, l[i], n)
            aj = pow(a * pow(gj, -1, n), order // pi**(j + 1), n)
            bj = pow(b, order // pi, n)
            cj = _discrete_log_pohlig_hellman(n, aj, bj, pi)
            l[i] += cj * pi**j

    d, _ = crt([pi**ri for pi, ri in f.items()], l)   # recombine
    return d
```

The inner loop is the standard prime-power lift: for a factor $p_i^{r_i}$ it recovers the exponent one base-$p_i$ digit at a time, each digit costing a discrete log in a group of size only $p_i$.

Driver:

```python
q, g, h, c1, c2 = (int(v) for v in enc_data)

print('factoring...')
factors = factorint(q - 1)          # smooth, so this returns quickly

y = dlog(q, c1, g, factors)         # c1 = g^y
s = pow(h, y, q)                    # shared secret h^y
m = (c2 * pow(s, -1, q)) % q        # strip the mask

print(long_to_bytes(m))
```

### Flag

```
ASCWG{H0w_5m0o0zy_E1G4m4l_c@n_B3_d18805fd}
```

"Smoozy" = **smooth**. The flag names its own weakness.

---

##  sign-hell

> Desc: A gate was opened to the hell. Can you find the way out? `nc 34.154.18.2 6951`

### Source

```python
import os
from sage.all import *

FLAG = os.getenv("FLAG", "ASCWG{XXXX}")

def get_prime():
    while True:
        p = 1
        for _ in range(9):
            p *= getrandbits(64)
        if is_prime(p+1):
            return p+1

def sign(M):
    S1 = int(pow(g, k, p))
    S2 = int(((M - a*S1) * inverse_mod(k, p-1))) % (p-1)
    return S1, S2

def verify(M, S1, S2):
    return pow(A, S1, p) * pow(S1, S2, p) % p == pow(g, M, p)

p = get_prime()
g = primitive_root(p)

a = secret = int.from_bytes(FLAG.encode(), "big")
A = pow(g, a, p)

k = getrandbits(256)
while gcd(k, p-1) != 1:
    k = getrandbits(256)

public = p, g, A
print(f"Public: ", public)
while True:
    m = int.from_bytes(os.urandom(32), "big")
    S1, S2 = sign(m)
    print(S1, S2, m)
```


### Analysis

This is the **ElGamal signature scheme**, and the flag _is_ the private key $a$, published as $A = g^a \bmod p$.

There are two independent weaknesses here, which is worth untangling.

### The advertised weakness — nonce reuse

`k` is generated **once**, outside the signing loop, then reused for every signature. That is fatal on its own. With two signatures $(S_1, S_2)$ and $(S_1, S_2')$ on messages $M, M'$ — note $S_1 = g^k$ is _identical_ across signatures, which makes the reuse visible at a glance — subtracting the signing equations gives

$$S_2 - S_2' \equiv (M - M')k^{-1} \pmod{p-1}$$

so $k$ follows, and then $a$ from $a \equiv (M - S_2 k)S_1^{-1}$. This is the classic attack, and the flag text calls it out.

### The weakness actually exploited — smooth p−1

But `get_prime` has the same flaw as `power-times`: $p - 1$ is a product of nine 64-bit values, hence **smooth**. So you don't need the signatures at all. $A = g^a \bmod p$ is a plain discrete log in a smooth-order group, and Pohlig–Hellman recovers $a$ directly.

That is strictly simpler than the nonce attack, no algebra mod $p-1$, no worrying about the non-invertibility of $\gcd(S_1, p-1) \ne 1$ that plagues ElGamal signature attacks. Read one line of output and solve one DLP.

### Exploit

```python
from pwn import remote
from sympy.ntheory.residue_ntheory import n_order, _discrete_log_pohlig_hellman
from sympy.ntheory.factor_ import factorint
from sympy.ntheory.modular import crt
from Crypto.Util.number import long_to_bytes

def dlog(n, a, b, factors):
    """same Pohlig-Hellman helper as power-times"""
    f = factors
    l = [0] * len(f)
    a %= n
    b %= n
    order = n_order(b, n)

    for i, (pi, ri) in enumerate(f.items()):
        for j in range(ri):
            gj = pow(b, l[i], n)
            aj = pow(a * pow(gj, -1, n), order // pi**(j + 1), n)
            bj = pow(b, order // pi, n)
            cj = _discrete_log_pohlig_hellman(n, aj, bj, pi)
            l[i] += cj * pi**j

    d, _ = crt([pi**ri for pi, ri in f.items()], l)
    return d
```

Only the public tuple is needed, the signature stream can be ignored entirely:

```python
io = remote("34.154.18.2", 6951)
p, g, A = eval(io.readline().decode().split(':')[1])

print('factoring...')
factors = factorint(p - 1)          # smooth by construction
print(factors)

a = dlog(p, A, g, factors)          # A = g^a  ->  a is the flag
print(long_to_bytes(a))
```

### Flag

```
ASCWG{R3uS31n9_G4m4l_NoNc3_S19n1n9_1s_50o_B4d_XXXX}
```

Note the mismatch: the flag advertises **nonce reuse**, but the smooth prime hands you the key without ever touching a signature. Two independent breaks in one challenge: the intended one and a shortcut. Worth checking `p-1` for smoothness before writing any signature algebra, that's what i actually did and it works 🤷‍♂️

---

## Takeaways

**Smooth group orders are the theme.** Both ElGamal challenges build their prime as _(product of small random factors) + 1_, making $p-1$ smooth and the discrete log easy. In `sign-hell` this shortcut bypasses the intended attack entirely.

The check is cheap and worth running before any deeper analysis:

```python
factorint(p - 1)   # all factors small?  -> Pohlig-Hellman
```
**Nonlinear is sometimes linear in disguise.** `perfect-encryption` looks like a nonlinear system needing Gröbner machinery, but substituting $z := xy$ reveals only three monomials and reduces it to $3\times3$ Gaussian elimination. Count the distinct monomials before reaching for heavy tooling — if there are no more monomials than equations, the system is linear in those monomials.

**Flag text is a hint, not a spec.** `sign-hell`'s flag names nonce reuse, but the actual solve used a different weakness. Solve the challenge in front of you, not the one the flag describes.
