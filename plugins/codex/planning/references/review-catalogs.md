# Review catalogs

Reference material for the `code-reviewer` agent. Load the section you need when a
protocol calls for it — none of this is needed to *start* a review, and most reviews
need at most one section.

---

## Structural principles (Protocol 3)

Name the specific principle; "bad design" is not a finding.

- **Single Responsibility** — a function or class doing two unrelated things.
- **Open-Closed** — modification required for an extension that should have been additive.
- **Liskov** — a subclass that breaks a contract the parent promised.
- **Interface Segregation** — a client forced to depend on methods it doesn't use.
- **Dependency Inversion** — a high-level module depending on a low-level detail.
- **Coupling & cohesion** — high coupling between modules that should be independent; low cohesion within a module that should be focused.

---

## Fowler smell catalog (Protocol 4)

Name smells by name. "This is bad" is not a review — "this is **Feature Envy**:
`OrderReport.calculateTotal` reads five fields off `Customer` without using any
`OrderReport` state, file `reports/order.py:84`" is a review.

Named smells to recognize (Fowler, *Refactoring* 2e):

- **Bloaters** — Long Method, Large Class, Primitive Obsession, Long Parameter List, Data Clumps
- **Object-Orientation abusers** — Switch Statements (for type-dispatch), Refused Bequest, Alternative Classes with Different Interfaces, Temporary Field
- **Change preventers** — Divergent Change, Shotgun Surgery, Parallel Inheritance Hierarchies
- **Dispensables** — Comments (hiding unclear code), Duplicate Code, Lazy Class, Data Class, Dead Code, Speculative Generality
- **Couplers** — Feature Envy, Inappropriate Intimacy, Message Chains, Middle Man

For each smell found, cite file and line, name the smell, and suggest a refactor from
Fowler's catalog (Extract Method, Move Method, Introduce Parameter Object, Replace
Conditional with Polymorphism, …).

---

## Security checklist (Protocol 5)

A floor, not an exhaustive list. Applies to every HTTP-exposed or untrusted-input-handling change.

1. **Injection** — every string interpolated into SQL, shell, LDAP, XPath, OS command, or log statement. Parameterize. (OWASP A03:2021; CWE-89, CWE-78, CWE-77)
2. **Authentication & session** — credentials compared in constant time? Sessions bound to the identity that created them? Tokens opaque random, not sequential? (OWASP ASVS V2, V3)
3. **Authorization** — every resource access authorized at the edge, not trusted from the request. Look for IDOR in URL/body/query params. (OWASP A01:2021; CWE-285, CWE-639)
4. **Input validation** — untrusted input hits a parser *before* any other code. Validate at the boundary, not "eventually somewhere." (OWASP ASVS V5)
5. **Output encoding** — untrusted data rendered in HTML/URL/JS contexts needs context-appropriate encoding. (OWASP A03; CWE-79)
6. **Secrets** — any credential, key, or token hardcoded or logged? Does the diff introduce a new secret-handling path bypassing the project's existing mechanism? (CWE-798, CWE-532)
7. **Cryptography** — weak primitive (MD5, SHA-1, ECB, CBC-without-integrity, custom crypto)? Recommend a project-standard replacement. (OWASP ASVS V6; NIST SP 800-131A)
8. **Deserialization / parsing** — untrusted bytes through a deserializer is a known RCE surface. Flag `pickle`, `unserialize`, `ObjectInputStream`, YAML `load`, or an XML parser with external entities enabled. (OWASP A08:2021; CWE-502)
9. **Path traversal & file handling** — user-influenced paths get canonicalized and verified against an allow-list. (CWE-22)
10. **Dependency risk** — new dependencies: well-known package? Latest stable version? Transitive vulnerability? (OWASP A06:2021)

**Safety-critical code** (drivers, medical, aviation, finance core) additionally gets NASA
Power of 10: bounded loops, no unbounded recursion, no dynamic allocation after init, at
least two assertions per function, check every return value of a non-void function.

---

## Test-review vocabulary (Protocol 6)

- Hidden dependencies that make tests brittle or impossible: `new Date()`, global singletons, filesystem reads in a pure-logic path.
- Meaningless assertions: a snapshot assertion carrying no semantic claim is theater (Meszaros, "Obscure Test").
- Valid reasons for a change to carry no test: characterization coverage, UI polish, generated code, throwaway tooling. "Ran out of time" is not one.

---

## Sources

- Google — *Code Review Developer's Guide* (google.github.io/eng-practices/review/)
- Martin Fowler — *Refactoring* 2e (2018); refactoring.com/catalog/
- Robert C. Martin — *Clean Code* (2008); SOLID
- Brian Kernighan & P.J. Plauger — *The Elements of Programming Style* (1978)
- Karl E. Wiegers — *Peer Reviews in Software* (2002)
- Michael Fagan — "Design and code inspections to reduce errors in program development" (IBM Systems Journal, 1976)
- OWASP — ASVS v4, WSTG v4.2, Top 10 (2021)
- MITRE — CWE Top 25 Most Dangerous Software Weaknesses
- CERT Secure Coding Standards (C, C++, Java)
- NASA / JPL — "The Power of 10: Rules for Developing Safety-Critical Code" (Holzmann, 2006)
- Gerard Meszaros — *xUnit Test Patterns* (test-smell vocabulary)
- Donald Knuth — "Literate Programming" (1984)
