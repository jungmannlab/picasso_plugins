# picasso_plugins
Collection of the approved Picasso plugins. Contributions are always welcome!

A plugin is a single Python (`.py`) file that adds new actions to a Picasso GUI.

## Installing plugins
The easiest way is Picasso itself: open **Plugins → Browse online plugins…** in any Picasso app (0.11 or newer). It lists everything in this repository's `index.json` and installs, updates and uninstalls with one click. Each entry also has a **View source** button that shows you the code before you install it, and a diff of what changed before you update.

You can also install by hand. Place your plugin `.py` file(s) in the user plugins folder:

- `~/.picasso/plugins` (on Windows this is `C:\Users\<your user name>\.picasso\plugins`).

This folder is created automatically the first time you run any Picasso GUI, and the **same folder is used for every installation type** (one-click installer, PyPI, conda or GitHub). The easiest way to open it is the **Plugins → Open plugins folder…** menu entry available inside any Picasso app.

A file copied in by hand is found but **not enabled**: Picasso will not run it until you tick its **Enabled** box in **Plugins → Browse online plugins…**, so a file appearing in that folder is never enough to make it execute.

Because the plugins folder lives in your home directory and not inside the Picasso installation, plugins are kept when you update Picasso and are not left behind when you uninstall it.

**NOTE**: With the one-click installer, plugins can only use packages that are installed with Picasso (the dependencies listed in `pyproject.toml`).

## What the hashes in this registry mean
Every entry in `index.json` carries the SHA-256 of the plugin file it points at. Picasso downloads the file, hashes it, and **refuses to install if the hash does not match**. The manifest, not the file, is therefore what pins a plugin's code: what you download is the file that was reviewed and published here, and it cannot change under people who already installed it without a commit to this repository that changes the hash — a visible, reviewable diff.

That is worth stating precisely, because it is easy to over-read:

- ✅ The file you get is the file published here.
- ✅ Published code cannot change silently; a change is a commit, and a commit is reviewed.
- ✅ You can read a plugin from inside Picasso before running it.
- ❌ It does **not** mean a plugin is safe to run.

A plugin is ordinary Python running inside Picasso with your full privileges: it can read and write your files, use the network and start other programs. Picasso does not sandbox plugins and does not claim to. What actually protects you is the review these plugins get before they are merged, the hashes that keep them from changing afterwards, and — for anything you care about — reading the source yourself. Only enable plugins whose authors you trust.

## For developers
To create a plugin, you can use the template provided in [picasso/plugin_template.py](https://github.com/jungmannlab/picasso/blob/master/plugin_template.py), then see [CONTRIBUTING.md](CONTRIBUTING.md) for how to submit it.

The short version: add the `.py` file under the directory of the app it extends, add an entry to `index.json`, run

```
python tools/hash_plugins.py --update
python tools/hash_plugins.py --check
```

and open a pull request with both files. Whenever a plugin's bytes change, its `version` and `sha256` must change with them in the same pull request — CI enforces this, because Picasso only offers an update when the version increases.

| Path | What it is |
| --- | --- |
| `index.json` | The manifest Picasso reads. The trust anchor. |
| `schema/index.schema.json` | Structure of the manifest, checked in CI. |
| `tools/hash_plugins.py` | `--check` validates the manifest; `--update` rewrites the hashes. |
| `tools/check_bumps.py` | Fails a pull request that changes a plugin without bumping its hash and version. |
| `tools/validate_schema.py` | Validates `index.json` against the schema (needs `jsonschema`). |

### For maintainers
Picasso fetches `index.json` from `main`, so anything merged is live for every user immediately — there is no staging step and no release to hold a mistake back. The CI checks are only a real gate if `main` is protected: required status checks, required review, no direct pushes. See the "Repository settings" section of [CONTRIBUTING.md](CONTRIBUTING.md).
