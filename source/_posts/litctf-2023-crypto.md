---
title: "LITCTF 2023 — Crypto Writeups"
date: 2024-04-10 10:00:00
categories:
  - CTF writeups
tags:
  - ctf
  - crypto
  - lcg
  - lattice
  - LLL
banner: /images/posts/litctf-2023-crypto/litctf-banner.png
cover: /images/posts/litctf-2023-crypto/litctf-banner.png
description: "Three linked LCG challenges from LITCTF 2023 — an elliptic-curve LCG broken with Pohlig–Hellman, a nested LCG broken by elimination, and sixteen noisy LCGs broken with a lattice."
---

Three crypto challenges, one generator, three completely different attacks.

![LITCTF 2023 — LexMACS](/siki-mahou/images/posts/litctf-2023-crypto/litctf-banner.png)

## Event details

|                   |                                                           |
| ----------------- | --------------------------------------------------------- |
| **Dates**         | Sat, 05 Aug 2023, 15:00 UTC — Tue, 08 Aug 2023, 03:59 UTC |
| **Location**      | On-line                                                   |
| **Format**        | Jeopardy                                                  |
| **Orgonizers**   |  [LIT CTF](https://ctftime.org/team/157660)                            |
| **Future weight** | 46.25                                                     |
| **Rating weight** | 33.53                                                     |

## About LITCTF

**LITCTF** is the CTF run by **LexMACS**, the Lexington High School Math, Algorithms and Computer Science club (Lexington, Massachusetts). It is a beginner-friendly, jeopardy-style competition covering the usual categories; crypto, rev, pwn, web, misc, with a difficulty curve that starts gently and gets genuinely sharp at the top end.

Challenge sources and infrastructure: **<https://github.com/LexMACS>**

This writeup covers the three linked crypto challenges from the 2023 edition. They form a deliberate progression around **linear congruential generators**:

| #   | Challenge        | Core idea                             | Tooling               |
| --- | ---------------- | ------------------------------------- | --------------------- |
| 1   | `ezlcg`          | LCG over an elliptic curve group      | Pohlig–Hellman        |
| 2   | `lcg-squared`    | LCG whose multiplier is itself an LCG | Algebraic elimination |
| 3   | `lcg-power-of-n` | 16 parallel LCGs with added noise     | LLL / lattice         |

All three end the same way: reconstruct the generator's next output, square it, use it as an AES-CBC key.

<!-- more -->

---

##  ezlcg

> _So I was reading a paper a while ago and it was about ECLCGs... I think idk I skimmed the paper. ECLCGs are probably just LCGs with elliptic curves though.... right?_

### Source

```python
#chall.sage 
from random import SystemRandom
random = SystemRandom()

def fun_prime(n): # not as smooth as my brain but should be enough
    while True:
        ps = 16
        p = 1
        for i in range(n//ps):
            p *= random_prime(2^ps)
        p += 1
        if is_prime(p):
            return p

def gen(b):
    p = fun_prime(b)
    E = EllipticCurve(GF(p), [random.randint(1, 2^b), random.randint(1,2^b)])
    return E, p, E.order()

C, p, order = gen(80)

# woah thats an lcg
class lcg:
    def __init__(self, C: EllipticCurve):
        self.order = order
        self.a = random.randint(1, self.order)
        self.x = C.gens()[0]
        self.b = self.x * random.randint(1, self.order)
    def next(self):
        self.x = (self.a * self.x + self.b)
        return self.x

prng = lcg(C)
x0 = prng.next()
x1 = prng.next()
x0, y0 = x0.xy()
x1, y1 = x1.xy()

v = int(prng.next().xy()[0])
k = pad(l2b(v**2), 16)
cipher = AES.new(k, AES.MODE_CBC, iv=iv)
enc = cipher.encrypt(pad(f,16))
```

Given data:

```python
x0 = 2029673067800379268
y0 = 1814239535542268363
x1 = 602316613633809952
y1 = 1566131331572181793
p  = 2525114415681006599
iv  = '6959dbf6bf22344d452c3831a3b68897'
enc = 'a490e177c3838c8f24d36be5ee10e0c9...'
```

### Analysis

The generator is an LCG whose state is a **curve point**:

$$X_{i+1} = a\thinspace X_i + \beta, \qquad X_0 = G$$

with $a$ a secret scalar and $\beta$ a secret point. You see $X_1, X_2$; the key comes from $X_3$.

Two things are conspicuously missing: the curve coefficients, and any way to relate the two published points.

### Step 1 — recovering the curve

The coefficients were never printed, but the curve is defined by

$$y^2 = x^3 + Ax + B \pmod p$$

and you have two points on it. Substituting each gives two equations that are **linear** in the unknowns $A, B$. Subtract them and $B$ cancels:

$$y_0^2 - y_1^2 - (x_0^3 - x_1^3) = A\thinspace (x_0 - x_1)$$

```python
F = GF(p)

A = (F(y0)^2 - F(y1)^2 - (F(x0)^3 - F(x1)^3)) / (F(x0) - F(x1))
B = F(y0)^2 - F(x0)^3 - A * F(x0)

E = EllipticCurve(F, [A, B])
P0 = E(x0, y0)
P1 = E(x1, y1)
```

### Step 2 — everything is a multiple of G

The decisive line in the constructor:

```python
self.b = self.x * random.randint(1, self.order)   # beta = r*G
```

The increment is not an arbitrary point, it is built **from $G$**. Combined with the seed being $G$ itself, the whole orbit stays inside the cyclic subgroup generated by $G$:

$$
\begin{aligned}
X_0 &= G &&= 1\cdot G\\
X_1 &= aG + rG &&= (a + r)\thinspace G\\
X_2 &= aX_1 + rG &&= \bigl(a(a+r) + r\bigr)G
\end{aligned}
$$

Scaling a multiple of $G$ and adding another multiple of $G$ never escapes. So each published point is $k_i\cdot G$ for some integer $k_i$, and if we can find those integers the point arithmetic collapses into ordinary modular arithmetic.

### Step 3 — the discrete logs are easy

`fun_prime` builds $p$ as a product of 16-bit primes plus one, so $p-1$ is smooth by construction. What actually matters for ECDLP is the **group order** $\#E$, which is a different number — so verify rather than assume:

```python
G = E.gens()[0]
n = G.order()

print("curve order factors:", factor(E.order()))
print("gen order factors:  ", factor(n))

# curve order factors: 3 * 47 * 2777 * 6448906331183
# gen order factors:   3 * 47 * 2777 * 6448906331183
```

The order factors into small primes, which makes this a **Pohlig–Hellman** instance: solve the DLP independently modulo each small prime power, then recombine with CRT. Sage applies this automatically:

```python
k0 = discrete_log(P0, G, operation='+')
k1 = discrete_log(P1, G, operation='+')
```

### Step 4 — solve the LCG over the scalars

Now the sequence is a plain integer LCG mod $n$, and we know three consecutive terms: $1$ (the seed), $k_0$, $k_1$.

$$
\begin{aligned}
X_0 &= k_0\cdot G\\
X_1 &= k_1\cdot G\\
k_0 &= a + r\\
k_1 &= a\cdot k_0 + r
\end{aligned}
\quad\Longrightarrow\quad
k_1 - k_0 = a\thinspace (k_0 - 1)
$$

```python
Zn = Zmod(n)
a = Zn(k1 - k0) / Zn(k0 - 1)
r = Zn(k0) - a
```

Step once more, map back to a point, take its $x$-coordinate:

```python
k2 = a * Zn(k1) + r
P2 = int(k2) * G
v  = int(P2.xy()[0])

key  = pad(l2b(v**2), 16)
flag = unpad(AES.new(key, AES.MODE_CBC, iv=iv).decrypt(enc), 16)
print(flag.decode())
```

### Full exploit — `ezlcg/solve.sage`

```python
from Crypto.Cipher import AES
from Crypto.Util.number import long_to_bytes as l2b
from Crypto.Util.Padding import pad, unpad

x0 = 2029673067800379268
y0 = 1814239535542268363
x1 = 602316613633809952
y1 = 1566131331572181793
p  = 2525114415681006599
iv  = bytes.fromhex('6959dbf6bf22344d452c3831a3b68897')
enc = bytes.fromhex('a490e177c3838c8f24d36be5ee10e0c9e244ac2e54cd306eddfb0d585d5f2753'
                    '5835fab1cd83d26a669e6c08096b58cc4cc4cb082f4534ce80fab16e21f119ad'
                    'c45a5f59d179ca3683b77a942e4cf4081e01d921a51ec3a3a48c13f850c04b80'
                    'c997367739bbde0a5415ff921d77a6ef')

F = GF(p)

A = (F(y0)^2 - F(y1)^2 - (F(x0)^3 - F(x1)^3)) / (F(x0) - F(x1))
B = F(y0)^2 - F(x0)^3 - A * F(x0)

E  = EllipticCurve(F, [A, B])
P0 = E(x0, y0)
P1 = E(x1, y1)

G = E.gens()[0]
n = G.order()
print("gen order factors:", factor(n))

k0 = discrete_log(P0, G, operation='+')
k1 = discrete_log(P1, G, operation='+')

Zn = Zmod(n)
a = Zn(k1 - k0) / Zn(k0 - 1)
r = Zn(k0) - a

k2 = a * Zn(k1) + r
v  = int((int(k2) * G).xy()[0])

key  = pad(l2b(v**2), 16)
flag = unpad(AES.new(key, AES.MODE_CBC, iv=iv).decrypt(enc), 16)
print(flag.decode())
```
### All together — Flag

```    
A = 710011040560831741
B = 2282801583147488997
curve order factors: 3 * 47 * 2777 * 6448906331183
gen order factors:   3 * 47 * 2777 * 6448906331183
k0 = 916472720818205535
k1 = 1673271260266693096
a = 1283473618943750015
r = 2158113518193477451
LITCTF{Youre_telling_me_I_cant_just_throw_elliptic_curves_on_something_and_make_it_100x_secure?_:<}
```



---

##  lcg-squared

> _Apparently lcgs are weak...... but my lcgs have doubled their power since they last met!_

### Source

```python
p = getPrime(64)

class lcg1:
    def __init__(self, n=64):
        self.a = random.randint(1, 2**n)
        self.b = random.randint(1, 2**n)
        self.x = random.randint(1, 2**n)
        self.m = p
    def next(self):
        ret = self.x
        self.x = (self.a * self.x + self.b) % self.m
        return ret

class lcg2:
    def __init__(self, n=64):
        self.lcg = lcg1(n)
        self.x = random.randint(1, 2**n)
        self.b = random.randint(1, 2**n)
        self.m = p
    def next(self):
        self.x = (self.lcg.next() * self.x + self.b) % self.m
        return self.x

lcg = lcg2()
print(p)
for x in range(5):
    print(lcg.next())

r = lcg.next()
k = pad(l2b(r**2), 16)
```

Given data:

```
p  = 11252070083876103037
y1 = 3157380704489980167
y2 = 202791412938399925
y3 = 705892353208348176
y4 = 5062131254806651470
y5 = 3846448923626044516
iv  = e5b9ad12334f59c192818a1f03044b3d
enc = 2d19c850490713b6019334c8fe1c8cc1...
```

### Analysis

Two nested generators. The inner one produces a stream of multipliers,

$$m_{i+1} = a\,m_i + b \pmod p$$

and the outer one consumes one per step:

$$y_i = m_{i-1}\,y_{i-1} + B \pmod p$$

> ⚠️ Mind the indexing: `lcg1.next()` returns the state **before** updating, while `lcg2.next()` updates and returns the **new** value. So the first printed value is $y_1 = m_0 y_0 + B$, and the key comes from $y_6$.

Unknowns: $a, b, B, m_0, y_0$ — five secrets, five published values. Nothing is noisy, so this is pure algebra.

And when a challenge is pure algebra, there is a tool that does the algebra for you. No cleverness required: write down what the code does, hand it to Sage, walk away.

### Step 1 — pick the unknowns

Two of the five secrets are worth dropping. $y_0$ appears in exactly one relation, $y_1 = m_0 y_0 + B$, so it brings one equation and one unknown. Drop $y_0$ and $m_0$ together and treat $y_1$ as the beginning of time. That leaves four unknowns:

$$a,\quad b,\quad B,\quad m_1$$

```python
R.<a, b, Bv, m1> = PolynomialRing(GF(p), order='lex')
```

### Step 2 — transcribe the challenge

Unroll the inner LCG symbolically. Each $m_j$ becomes a polynomial in $a, b, m_1$ : 

```python
m = {1: m1}
for j in (1, 2, 3, 4):
    m[j + 1] = a * m[j] + b
```

Then the outer recurrence $y_{j+1} = m_j y_j + B$, rearranged to equal zero because that is what an ideal wants:

```python
eqs = [m[j] * F(y[j]) + Bv - F(y[j + 1]) for j in (1, 2, 3, 4)]
```

Four equations, four unknowns. That is the entire model, a direct transcription of the challenge source, with no insight applied.

### Step 3 — let the machine eliminate

```python
I = R.ideal(eqs)
G = I.groebner_basis()
sols = I.variety()
```

Under lex ordering the basis comes back triangulated: the last element is univariate, the one before reintroduces a single variable, and so on. Sage solves that chain and `variety()` hands back the roots. Step forward to $m_5$, compute $y_6$, decrypt.

### Full exploit — `lcg-squared/intended-solve.sage`

```python
from Crypto.Cipher import AES
from Crypto.Util.number import long_to_bytes as l2b
from Crypto.Util.Padding import pad, unpad

p = 11252070083876103037
y = [None,
     3157380704489980167,
     202791412938399925,
     705892353208348176,
     5062131254806651470,
     3846448923626044516]

iv  = bytes.fromhex('e5b9ad12334f59c192818a1f03044b3d')
enc = bytes.fromhex('2d19c850490713b6019334c8fe1c8cc1fb0cf8f67deb9245763222784300598c'
                    '1675b13f504b8178c3ed349b3978b05bfa61935ab4ce9427742442d64d85c669'
                    '1b97c5b4d55c553ccb05b617a94e2a23')

F = GF(p)
R.<a, b, Bv, m1> = PolynomialRing(F, order='lex')

# lcg1:
m = {1: m1}
for j in (1, 2, 3, 4):
    m[j + 1] = a * m[j] + b

# lcg2:
eqs = [m[j] * F(y[j]) + Bv - F(y[j + 1]) for j in (1, 2, 3, 4)]

I = R.ideal(eqs)
for sol in I.variety():
    A, Bb, BB, M1 = sol[a], sol[b], sol[Bv], sol[m1]
    mm = M1
    for _ in range(4):
        mm = A * mm + Bb

    y6 = mm * F(y[5]) + BB
    key = pad(l2b(int(y6)**2), 16)

    flag = unpad(AES.new(key, AES.MODE_CBC, iv=iv).decrypt(enc), 16)
    print(flag.decode())

```

### Flag

```
LITCTF{groebner_so_op_this_would_be_very_awkward_if_you_used_resultants}
```

`groebner_so_op`, no argument here. Four lines of transcription and Sage did the rest.

---

### Doing it the awkward way

But hold on. The flag doesn't just praise Gröbner, it **taunts** you: _"this would be very awkward if you used resultants."_

Awkward, you say. Let's find out how awkward.

Resultants eliminate one variable from two polynomials at a time. Doing that by hand is basically the same idea, just done by inspection, and it turns out this system is small enough that you can see straight through it. So what follows is the elimination Sage was doing for us, but worked out by hand. Honestly, it's more fun this way.

#### Step 1 — five unknowns collapse into one

Invert the outer recurrence:

$$m_{i-1} = \frac{y_i - B}{y_{i-1}}$$

For $i = 2,\dots,5$ both $y$'s on the right are known. Define

$$u_j := m_j = \frac{y_{j+1} - B}{y_j}, \qquad j = 1,2,3,4$$

Each $u_j$ is a **linear function of the single unknown $B$**. Four of the five secrets just evaporated — $a$, $b$, $m_0$ and $y_0$ are all gone, and only $B$ remains.

> Start at $j = 1$: taking $j = 0$ would need $y_0$, the unpublished seed. Same reason we dropped it above.

```python
F = GF(p)
R.<Bv> = PolynomialRing(F)
u = {j: (F(y[j+1]) - Bv) / F(y[j]) for j in (1, 2, 3, 4)}
```

#### Step 2 — eliminate a and b

The four $u_j$ are consecutive terms of the inner LCG, so $u_{j+1} = a u_j + b$. Consecutive differences kill $b$:

$$u_3 - u_2 = a\,(u_2 - u_1), \qquad u_4 - u_3 = a\,(u_3 - u_2)$$

Dividing one by the other kills $a$:

$$\boxed{(u_3 - u_2)^2 = (u_4 - u_3)(u_2 - u_1)}$$

Every bracket is linear in $B$, so this is a **quadratic in $B$ over $\mathbb{F}_p$** — at most two roots.

```python
eq = (u[3] - u[2])^2 - (u[4] - u[3]) * (u[2] - u[1])
roots = [r for r, _ in eq.roots()]
```

Two subtractions and one division, and every unknown but $B$ is gone. Note the sample budget: four inner terms are the exact minimum for two differences and one ratio. One fewer output and this route closes entirely, the author left precisely enough rope.

#### Step 3 — unroll and filter

For each candidate $B$, recover $a$ and $b$, then use the fourth relation as a **consistency check** to reject the wrong root, no need to rely on garbled plaintext:

```python
for Bc in roots:
    uu = {j: (F(y[j+1]) - Bc) / F(y[j]) for j in (1, 2, 3, 4)}
    if uu[2] == uu[1]:
        continue
    a = (uu[3] - uu[2]) / (uu[2] - uu[1])
    b = uu[2] - a * uu[1]
    if uu[4] != a * uu[3] + b:      
        continue
    m5 = a * uu[4] + b
    y6 = m5 * F(y[5]) + Bc
```

#### Full exploit — `lcg-squared/solve.sage`

```python
from Crypto.Cipher import AES
from Crypto.Util.number import long_to_bytes as l2b
from Crypto.Util.Padding import pad, unpad

p = 11252070083876103037
y = [None,
     3157380704489980167,
     202791412938399925,
     705892353208348176,
     5062131254806651470,
     3846448923626044516]

iv  = bytes.fromhex('e5b9ad12334f59c192818a1f03044b3d')
enc = bytes.fromhex('2d19c850490713b6019334c8fe1c8cc1fb0cf8f67deb9245763222784300598c'
                    '1675b13f504b8178c3ed349b3978b05bfa61935ab4ce9427742442d64d85c669'
                    '1b97c5b4d55c553ccb05b617a94e2a23')

F = GF(p)
assert all(F(y[j]) != 0 for j in range(1, 6)), "y_j must be invertible"

R.<Bv> = PolynomialRing(F)
u = {j: (F(y[j+1]) - Bv) / F(y[j]) for j in (1, 2, 3, 4)}

eq = (u[3] - u[2])^2 - (u[4] - u[3]) * (u[2] - u[1])
roots = [r for r, _ in eq.roots()]
print("candidate B:", roots)

for Bc in roots:
    uu = {j: (F(y[j+1]) - Bc) / F(y[j]) for j in (1, 2, 3, 4)}

    if uu[2] == uu[1]:                       
        continue
    a = (uu[3] - uu[2]) / (uu[2] - uu[1])
    b = uu[2] - a * uu[1]

    if uu[4] != a * uu[3] + b:               
        print(f"B = {Bc} rejected (inner lcg inconsistent)")
        continue

    m5 = a * uu[4] + b
    y6 = m5 * F(y[5]) + Bc
    print(f"B = {Bc}\na = {a}\nb = {b}\ny6 = {y6}")

    key = pad(l2b(int(y6)**2), 16)
    try:
        flag = unpad(AES.new(key, AES.MODE_CBC, iv=iv).decrypt(enc), 16)
        print(flag.decode())
    except Exception as e:
        print("decrypt failed:", e)
```

Same flag, no Sage-specific machinery, and honestly a nicer way to spend M0R3 T1M3 👀.


---

##  lcg-power-of-n

> _1 lcg isnt enough..... 2 lcgs isnt enough...? Well I will never use one of those inferior prngs, but idk how to make this secure. Oh wait I know, I should add even more lcgs!_

### Source

```python
n = 64
d = 16
P = getPrime(n)

A = random.getrandbits(n)
B = random.getrandbits(n)
xs = []

class lcg:
    def __init__(self):
        self.a = A                       # shared
        self.b = B                       # shared
        self.x = random.getrandbits(n)   # only this differs
        xs.append(self.x)
        self.m = P
    def next(self):
        self.x = (self.a * self.x + self.b) % self.m
        return self.x + random.randint(-P//(2**9) + 1, P//(2**9))  # whats life without a lil error!

lcgs = [lcg() for _ in range(d)]
print(f"{P = }\n{xs = }\nout = {[x.next() for x in lcgs]}")

k = pad(l2b(A**2), 16)
```

### Analysis

Sixteen generators, but read the constructor carefully; `A` and `B` are **module-level constants shared by all of them**. Only the seeds differ, and every seed is printed. Each is stepped once:

$$\texttt{out}_i = \bigl(A x_i + B \bmod P\bigr) + e_i, \qquad |e_i| \le E := \left\lfloor P/2^9 \right\rfloor$$

Target: $A$ alone. $B$ is never needed for the key.

Unlike `lcg-squared`, the relations are **not exact**; each carries an unknown error, so elimination gets you nowhere. But the errors are small: the noise is bounded by $P/2^9$, so each unknown is confined to a range 512 times narrower than the modulus. Small unknowns in modular relations is the Hidden Number Problem — which means a lattice.
### Step 1 — difference away B

Fix sample 0 as reference:

$$t_i := x_i - x_0, \qquad u_i := \texttt{out}_i - \texttt{out}_0$$

$B$ cancels, leaving fifteen relations in one unknown:

$$\boxed{\thickspace u_i - A\thinspace t_i \equiv \varepsilon_i \pmod P, \qquad |\varepsilon_i| \le 2E\thickspace }$$

```python
t = [(xs[i] - xs[0]) % P for i in range(1, 16)]
u = [(out[i] - out[0]) % P for i in range(1, 16)]
```

### Step 2 — the lattice

Build the $17\times17$ basis with $K := 2E$:

$$
M=
\begin{pmatrix}
P\thinspace I_{15} & \mathbf{0} & \mathbf{0}\\
t_1 \cdots t_{15} & K/2^{64} & 0\\
u_1 \cdots u_{15} & 0 & K
\end{pmatrix}
$$

The combination $A\cdot(\text{t-row}) - (\text{u-row})$, reduced by the $P$-rows, gives

$$v = \Bigl(-\varepsilon_1,\dots,-\varepsilon_{15},\ A\tfrac{K}{2^{64}},\ -K\Bigr)$$

Every coordinate is bounded by $K$, so $\|v\| \approx \sqrt{17}\thinspace K$. The two scaling columns balance the vector and are what let you read $A$ back out.

Will LLL find it? Our target vector has every coordinate bounded by $K$, which makes it far shorter than a typical vector in a lattice this size, and short vectors are exactly what LLL hunts for. So run the reduction and look through the reduced basis for the row carrying our signature: the one whose last entry is $\pm K$.

### Step 4 — read A back and verify

Find the reduced row whose last entry is $\pm K$; its neighbour holds $\pm A\thinspace K/2^{64}$.

Verification must use the **centred** residual. The noise is added _after_ the modular reduction and can be negative, so reducing into $[0,P)$ would break every smallness test:

```python
def centre(v, m):
    v %= m
    return v - m if v > m // 2 else v
```

### Full exploit — `lcg-power-of-n/solve.sage`

```python
from Crypto.Cipher import AES
from Crypto.Util.number import long_to_bytes as l2b
from Crypto.Util.Padding import pad, unpad

P = 13131324022074804079
xs = [818660445928296216, 4304663454498751845, 8078700408623796749, 1778475378977596779,
      12824664706131170268, 10420761949177186522, 6845546710088149747, 14110579524723166104,
      14897039251261399439, 3774734634946337646, 15279708159821145288, 8906678690214943251,
      11119738051050899844, 1841284253154569101, 2783084396686288544, 11854686581894585340]
out = [12991798441769803093, 7498783580600923236, 9188781492566527528, 12845033212340891357,
       5565380757767757248, 11625073182050856072, 12465139570398461776, 1031252012263875382,
       12115687014180020079, 116379706792989403, 9685641342885785654, 9806645816574735805,
       9466308272233367959, 12187856198301834495, 12544820285589854231, 6524905402046307976]

iv  = bytes.fromhex('1aaa82a3283e8e313b8a339438aa40d4')
enc = bytes.fromhex('57b8e82a49a391d980084ba15d00c38e'
                    '11f7906a8b2e2138ca6444791c629ade'
                    'fef4c592535f086473c8bc4d00c63ffb')

E    = P // 2**9      
K    = 2 * E          
BITS = 64             

t = [(xs[i] - xs[0]) % P for i in range(1, 16)]
u = [(out[i] - out[0]) % P for i in range(1, 16)]
d = len(t)

def centre(v, m):
    """representative of v mod m in (-m/2, m/2]"""
    v %= m
    return v - m if v > m // 2 else v

scale = QQ(K) / QQ(2**BITS)
M = Matrix(QQ, d + 2, d + 2)
for i in range(d):
    M[i, i]     = P
    M[d, i]     = t[i]
    M[d + 1, i] = u[i]
M[d, d]         = scale
M[d + 1, d + 1] = K

L = M.LLL()

cands = []
for row in L:
    if abs(row[d + 1]) != K:
        continue
    a = row[d] / scale
    if a not in ZZ:
        continue
    a = abs(ZZ(a))
    if 0 < a < 2**BITS:
        cands.append(a)
print("candidates:", cands)

for A in cands:
    B = (out[0] - A * xs[0]) % P          
    if not all(abs(centre(out[i] - A * xs[i] - B, P)) <= 2 * E for i in range(16)):
        print(f"A = {A} rejected (residuals too large)")
        continue

    print(f"A = {A}")
    key = pad(l2b(int(A)**2), 16)
    flag = unpad(AES.new(key, AES.MODE_CBC, iv=iv).decrypt(enc), 16)
    print(flag.decode())

```

**Notes.** The lattice is built over `QQ` because the scaling factor $K/2^{64}$ is not an integer; multiplying every row by $2^{64}$ to stay in `ZZ` gives the same lattice. If `candidates` comes back empty, that is the thin $2^{1.25}$ margin rather than a logic error — try `M.BKZ(block_size=20)`, then shrink `K`.

### Flag

```
LITCTF{Its_all_HNP?_Always_has_been}
```

---

## Takeaways

The three challenges are a tour of _which tool matches which structure_:

| Structure                          | Tool                                                                    |
| ---------------------------------- | ----------------------------------------------------------------------- |
| Relations in an unfamiliar group   | Move to the group where they are linear — here, scalars mod $n$ via DLP |
| Exact polynomial relations         | Elimination — by hand, via resultants, or Gröbner                       |
| Relations with small unknown slack | Lattice reduction (LLL)                                           |

The dividing line between challenges 2 and 3 is a single line of code — `+ random.randint(...)`. With exact relations, algebra wins outright. Add bounded noise and algebra becomes useless while geometry takes over. Recognising which side of that line a problem sits on is most of the work.

A secondary theme runs through all three: **smallness is a weakness**. A smooth group order, a nonce shorter than the modulus, an error bounded well below $P$ each one hands you the structure needed to break the system.
