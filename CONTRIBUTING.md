# Contributing a plugin

Thanks for wanting to share your work. Please read the short section on what
this registry does and does not guarantee before you start — it explains why
the steps below are what they are.

## What this registry guarantees

Picasso installs a plugin by downloading the `.py` file this repository points
at, hashing it, and comparing the result with the `sha256` published in
`index.json`. It refuses to install on any mismatch.

That means **the manifest, not the file, is what pins a plugin's code**: your
plugin cannot change under people who already installed it without a commit
here that changes its `sha256` — a visible, reviewable diff.

It does **not** mean a plugin is safe. A plugin is ordinary Python running
inside Picasso with the user's full privileges: it can read and write their
files, use the network, and start other programs. Picasso deliberately does not
pretend to sandbox plugins. The only things standing between a user and a bad
plugin are the review this repository does, the hashes that stop the code
changing afterwards, and the user reading the source (Picasso's plugin browser
has a **View source** button). Please help all three work.

## Submitting a plugin

1. Fork this repository and create a branch.
2. Add your plugin as a single `.py` file under the directory named after the
   Picasso app it extends: `render/`, `localize/`, `filter/`, `average/`,
   `design/`, `simulate/`, `nanotron/` or `spinna/`. Start from
   [`plugin_template.py`](https://github.com/jungmannlab/picasso/blob/master/plugin_template.py).
3. Add an entry to `index.json`:

   ```json
   {
     "id": "my_plugin",
     "file": "render/my_plugin.py",
     "sha256": "",
     "display_name": "My plugin",
     "app": "render",
     "description": "One or two sentences. State any hardware or dependency requirement here.",
     "author": "Your Name",
     "version": "1.0.0",
     "min_picasso_version": "0.11.0"
   }
   ```

   - `id` may contain only letters, digits, `_` and `-`, and must not start
     with `-`. It becomes the file name (`<id>.py`) in the user's plugins
     folder, so **changing it later orphans every existing install** — pick it
     carefully.
   - `app` must be one of the eight names above.
   - `min_picasso_version` is optional; set it if your plugin uses anything
     added in a particular Picasso release. Older clients then list it as
     incompatible instead of failing at import time.

4. Fill in the hash automatically:

   ```
   python tools/hash_plugins.py --update
   ```

5. Check everything before pushing:

   ```
   python tools/hash_plugins.py --check
   ```

6. Commit the plugin file **and** the updated `index.json` together, and open a
   pull request.

## Updating an existing plugin

Every time the bytes of a plugin file change, **both** `version` and `sha256`
must change in the same pull request. `tools/hash_plugins.py --update` writes
the hash and warns you if the version stayed the same; CI fails the PR if
either is missing.

Leaving the version alone is not a cosmetic mistake: Picasso only offers an
update when the manifest version is higher than the installed one, so users
would keep running the old code indefinitely while the registry claims they are
up to date.

## Review checklist for maintainers

Do not merge on the manifest diff alone. **Read the whole diff of the plugin
file**, every time, including updates to plugins already in the registry —
that is the review this registry's guarantee rests on.

Reject, or require justification in the PR description, when the plugin:

- makes network requests, or contacts any service other than one central to
  what the plugin is for;
- uses `subprocess`, `os.system`, or otherwise runs external programs;
- uses `eval`, `exec`, `compile`, or builds code from strings;
- loads `pickle`, `dill`, `joblib` or `torch.load` data from anywhere the user
  did not explicitly choose;
- writes outside paths the user picked in a dialog — in particular the Picasso
  installation, the plugins folder itself, or anywhere in the home directory;
- installs or downloads packages at runtime (`pip`, `conda`, `urlretrieve`);
- reads credentials, tokens, environment variables or the clipboard;
- is obfuscated, minified, base64-encoded, or otherwise not straightforwardly
  readable.

Also confirm before merging:

- the author is identifiable, and the code is theirs to publish;
- the changed bytes come with a bumped `version` and a regenerated `sha256`;
- CI is green — but treat it as a floor, not the review. It verifies structure
  and hashes; it cannot tell you what the code does.

## Repository settings

The checks above only protect anyone if GitHub enforces them. These cannot be
set from repository contents and must be configured once, by an admin, under
**Settings → Branches → Branch protection rules** for `main`:

- **Require status checks to pass before merging**, with `verify` (from
  `.github/workflows/verify-registry.yml`) selected;
- **Require a pull request before merging**, with at least one approving
  review;
- **Do not allow bypassing the above settings**, including for administrators.

Picasso reads `index.json` from `main` directly, so anything merged is live
for every user immediately. There is no staging step and no release to hold a
mistake back — a bad merge is the failure mode this repository is designed
against.
