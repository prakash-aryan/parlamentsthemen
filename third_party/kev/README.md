# Kev, adapted to Apertus 1.5

The decision model is trained and served with Kev (https://github.com/jaredpalmer/kev, Apache-2.0), an open implementation of the decision-model idea behind TypeSafe's System One models.

We used upstream commit `1f04cfa` and changed one file, `kev/model.py`, so that Kev accepts the text part of Apertus 1.5 8B; the change is in `apertus.patch`.

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
git checkout 1f04cfa
git apply ../apertus.patch
```

Kev's licence (Apache-2.0) applies to the patched files.
