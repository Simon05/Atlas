# Refine a scan with your own agent

Use your existing agent to improve suggestions—not to take over file operations.
Start with a folder you scanned in Atlas. Give the agent the exact scope and point it
to `AGENTS.md` and `skills/atlas-cleanup/SKILL.md`.

## 1. Export context

In Cleanup, expand **Refine suggestions with your AI agent → Export scan context**.
This includes item names, sizes, fingerprints, suggested actions and scan evidence,
without file contents. The command-line helper can also list saved scans and export
basic item metadata:

```sh
python3 scripts/agent_context.py --list
python3 scripts/agent_context.py --source YOUR_SOURCE_ID --out .atlas/agent-context.json
```

Replace `YOUR_SOURCE_ID` with the exact source ID printed by `--list`. The browser export also
includes relation summaries and any suggestion refinements currently loaded there.

## 2. Ask for useful, bounded analysis

A useful request is:

> Review this exported Atlas context. Group the easy decisions, explain uncertain
> projects and suggest a few sensible destinations. Use exact evidence for duplicate
> and ZIP claims. Read additional files only inside the folder I authorize. Do not
> execute projects, read secrets, move files or delete anything. Return an Atlas proposal.

Share project intent when it matters: active work, reusable resources, or an abandoned
experiment. Absence of a reference is not proof of an orphan. Shared libraries and
matching source trees do not prove that a whole project is redundant.

## 3. Return proposal JSON

Save analysis in `.atlas/`, outside the scanned source folder. Copy these values from
the context; the values here are illustrative:

```json
{
  "schemaVersion": 1,
  "sourceRoot": "/Example/Downloads",
  "scannedAt": 1794700800,
  "suggestions": [
    {
      "path": "Moodboard.svg",
      "fingerprint": "copy-the-exact-item-fingerprint-from-context",
      "status": "Move",
      "target": "Design Library/Moodboards",
      "reason": "Reusable visual reference. No resolved incoming project reference was found in this scan; external uses remain unknown."
    }
  ]
}
```

Statuses: `Keep`, `Move`, `Trash`, `Undecided`. Moves require relative destinations;
absolute paths, empty segments and `..` are rejected. Other statuses can omit `target`.
Keep item paths and fingerprints exact. Use `Undecided` when owner input is needed.

## 4. Import and decide

Import the proposal in Cleanup's same disclosure. Atlas rejects stale or mismatched
snapshots, repeated items and invalid destinations. The proposal updates suggestion
context while preserving your existing decisions. Project, reference and retained-copy
checks still apply. Your normal Keep / Move / Trash choices remain the source of the plan.

Atlas does not call a model provider. Your agent may do so; metadata can still be private.
Never upload personal scans, proposals or filenames in public issues or pull requests.
