#!/usr/bin/env python3
import os
import subprocess
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

KAS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'kas')

"""
update_repo_refs.py

This script walks the 'kas' directory and its subdirectories to find all .yml files. For each YAML file, it looks for repositories defined under the 'repos' section. If a repository has both a 'url' and a 'branch', the script fetches the latest commit hash for that branch using 'git ls-remote'. It then inserts or updates a 'commit' key (immediately after 'branch') with the latest commit hash. The script preserves YAML formatting and only updates files if necessary.

Intended for use with kas project configuration files to ensure all repositories are pinned to the latest commit on their specified branch.
"""
# Requirements:
#   - Python 3
#   - ruamel.yaml (install with: pip install ruamel.yaml)
#   - git (must be installed and in your PATH)

def find_yml_files(root):
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if fname.endswith('.yml'):
                yield os.path.join(dirpath, fname)

def get_latest_ref(url, branch):
    try:
        result = subprocess.run(
            ['git', 'ls-remote', url, branch],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True
        )
        for line in result.stdout.splitlines():
            if line.endswith(f'\trefs/heads/{branch}') or line.endswith(f'\t{branch}'):
                return line.split('\t')[0]
        # fallback: first line
        if result.stdout.strip():
            return result.stdout.strip().split('\t')[0]
    except Exception as e:
        print(f"Failed to get ref for {url} {branch}: {e}")
    return None

def update_refs_in_file(yml_path):
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(yml_path, 'r') as f:
        data = yaml.load(f)

    if not data or 'repos' not in data:
        return False

    repos = data['repos']
    changed = False
    for repo_name, repo_data in repos.items():
        if not isinstance(repo_data, CommentedMap):
            continue
        url = repo_data.get('url')
        branch = repo_data.get('branch')
        if url and branch:
            latest_ref = get_latest_ref(url, branch)
            if latest_ref:
                # Insert or update commit after branch
                keys = list(repo_data.keys())
                if 'commit' in repo_data:
                    if repo_data['commit'] != latest_ref:
                        repo_data['commit'] = latest_ref
                        changed = True
                else:
                    # Insert after branch
                    idx = keys.index('branch') + 1
                    items = list(repo_data.items())
                    items.insert(idx, ('commit', latest_ref))
                    new_map = CommentedMap(items)
                    # preserve comments
                    for k in repo_data:
                        new_map.yaml_set_comment_before_after_key(k, before=repo_data.ca.items.get(k, [None, None, None, None])[2])
                    repos[repo_name] = new_map
                    changed = True
    if changed:
        with open(yml_path, 'w') as f:
            yaml.dump(data, f)
    return changed

def main():
    for yml_file in find_yml_files(KAS_DIR):
        print(f"Processing {yml_file}")
        changed = update_refs_in_file(yml_file)
        if changed:
            print(f"Updated refs in {yml_file}")

if __name__ == '__main__':
    main() 
