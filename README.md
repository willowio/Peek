
# Peek

*take a look around.*

Peek is a little macOS terminal tool I made to see what's installed and running on my Mac.

It started as a simple idea and somehow turned into a whole project. It's not trying to be the next big thing or anything. I just wanted to make it, and figured someone else might find it useful too.

![Peek screenshot](docs/images/peek.png)

## what it does

Browse installed apps, Homebrew packages, security info, services, and developer tools.

Mostly just looking around.

## installation

Requires macOS and Python 3.11 or newer.

```sh
(
  set -e
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  curl -fsSL \
    https://github.com/willowio/Peek/releases/download/v0.1.0/peek-bootstrap.py \
    -o "$tmp/peek-bootstrap.py"

  printf '%s  %s\n' \
    '22b700b5149d6af68703ebc83d02e2aafec0cad4e9a6ad4bb70cea1662044d0e' \
    "$tmp/peek-bootstrap.py" | shasum -a 256 -c -

  python3 "$tmp/peek-bootstrap.py" \
    --url https://github.com/willowio/Peek/releases/download/v0.1.0/peek-0.1.0-install.zip \
    --sha256 c367557e84ea128971916985f67a0e1faf94189d7f08d2f8c3c3e4c7171c489e
)
```

Once installed, run:

```sh
peek
```

Press `?` for help.

## uninstall

```sh
peek gtfo
```

---

made by willow.
