<!--
Thanks for contributing! Please fill this in — the answers are what reviewers
read the code against. See CONTRIBUTING.md for the full process.
-->

## What does this plugin do?

<!-- One or two paragraphs. Which Picasso app does it extend, and what does it add? -->

## What does it access?

<!--
Required. Be specific and honest; reviewers will check the code against this.
Say "none" where that is the answer.

- Files it reads or writes (and whether the user picks the paths):
- Network requests it makes (which hosts, and why):
- External programs it runs:
- Anything else notable (large downloads, GPU requirements, long-running work):
-->

## Requirements

<!-- Hardware (e.g. CUDA GPU) and any package beyond Picasso's own dependencies.
Note that one-click-installer users only have the packages Picasso ships with. -->

## Checklist

- [ ] The plugin is a single `.py` file under the directory of the app it extends
- [ ] I added or updated its entry in `index.json`
- [ ] I ran `python tools/hash_plugins.py --update` and committed the new `sha256`
- [ ] `python tools/hash_plugins.py --check` passes
- [ ] **For an update to an existing plugin:** I bumped `version` in the same commit
- [ ] The code contains no `eval`/`exec`, no obfuscated or encoded payloads, and no runtime package installation
- [ ] I am the author, or I have the right to publish this code, and the licence permits it
- [ ] I understand that this file will run on other people's computers with their full privileges
