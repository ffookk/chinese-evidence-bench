# Privacy and contribution checks

## Measures in place

- Demonstrations and tests use fictional content; personal inputs and outputs belong in ignored local directories.
- Commits use a GitHub noreply email address; author and committer metadata are checked before submission.
- CI has read-only repository permissions, receives no project secrets, and does not upload input, output, or test files as artifacts.
- GitHub Actions are pinned to specific commits and should be reviewed again when updated.
- Privacy diagnostics display only rule names and file indices, without echoing matched values.

## Before submitting

```sh
git add <files-to-submit>
python3 scripts/privacy_check.py --history
python3 -m unittest discover -s tests -v
```

The check covers tracked working-tree text, staged contents, text and filenames in reachable commits, and commit metadata. It detects common secret formats, private conversation links, local user paths, non-example email addresses, and sensitive directories. Binary files and symbolic links require manual handling.

After creating a local commit and before pushing, rerun the privacy check with `--history` to cover the new author, committer, and commit message.

This heuristic check cannot identify every kind of personal information, custom credential, or image content. It does not inspect untracked files, GitHub issue or PR bodies, remotely unreachable history, platform retention records, or existing external copies. Review diffs and collaboration content before publication.

Ignore rules do not remove files already tracked by Git. Check the staged file list with `git diff --cached --name-only` before submitting.

## If a problem is found

Stop submitting changes and locate and remove the material locally. Do not paste sensitive values into issues, PRs, discussions, screenshots, or logs. If a credential was exposed, revoke or rotate it before addressing repository history. Ordinary issues should record only remediation status without sensitive values.
