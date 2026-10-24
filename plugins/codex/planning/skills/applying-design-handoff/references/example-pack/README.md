# Example handoff pack

A minimal, well-formed **local** handoff pack, used both as a worked example of the
[handoff-pack-format.md](../handoff-pack-format.md) contract and as the green fixture for
`../../scripts/validate-handoff-pack.py`.

```
example-pack/
  handoff/
    handoff.json            # manifest: components + screens index
    tokens.json             # design tokens used on the canvas
    components/
      button.json           # anatomy + variants + states
      card.json
    screens/
      home.json             # layout region tree
    assets/
      logo.svg              # referenced asset
```

Validate it:

```
python3 ../../scripts/validate-handoff-pack.py .
```

Expected: exit 0, with a normalized manifest reporting `tokens`, `components` (2),
`layout` (1), and `assets` (1), and `root` pointing at `example-pack/handoff`. This is a
*structural* example — values are illustrative, not a real product design.
