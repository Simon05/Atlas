# Publishing Atlas

Atlas is MIT licensed. The public repository is
[Simon05/Atlas](https://github.com/Simon05/Atlas).

1. Run the checks in `CONTRIBUTING.md` and verify a clean clone starts with the folder chooser.
2. Keep `.atlas/`, `work/`, `outputs/`, private plans and local environments excluded. Never force-add them. Public images in `docs/assets/` must use synthetic files.
3. Push reviewed source changes and keep private vulnerability reporting enabled.
4. Keep the README clone URL, CI badge, issue links and star-history URL aligned with the public repository. Topics: `macos`, `folder-cleanup`, `duplicates`, `local-first`, `ai-agents`.
5. Wait for the hosted checks to pass before announcing a release.
6. The README uses this live star-history chart; a new repository may have little or no history yet.

```md
## Star history

[![Star History Chart](https://api.star-history.com/svg?repos=Simon05/Atlas&type=Date)](https://star-history.com/#Simon05/Atlas&Date)
```

The chart makes a request to a third-party service when the README is viewed. Atlas itself
does not load external charts or make analytics requests.

The compact README hierarchy was inspired by [REA](https://github.com/morluto/rea),
while keeping Atlas's scope and setup much smaller.
