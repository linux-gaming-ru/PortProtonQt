#!/bin/bash
set -euo pipefail

GITHUB_REPOS=("linux-gaming-ru/PortProtonQt")
GITEA_REPO="Linux-Gaming/PortProtonQt"
GITEA_URL="https://git.linux-gaming.ru"

jq_format='def format_downloads: if . < 1000 then tostring else ((. / 100 | round) / 10 | tostring) + "k" end;'

jq_total='[.[].assets[] | select(.name | test("\\.(zsync|sha256)$|steam-compat") | not) | .download_count] | add // 0'

echo "=== PortProtonQt Download Stats ==="
echo

echo "--- GitHub (${GITHUB_REPOS[*]}) ---"
GH_RAW=$(for repo in "${GITHUB_REPOS[@]}"; do
    curl -sfL "https://api.github.com/repos/${repo}/releases?per_page=100"
done | jq -s 'add')
GH_COUNT=$(echo "$GH_RAW" | jq "$jq_total")
GH_RELEASES=$(echo "$GH_RAW" | jq 'length')
echo "Releases: $GH_RELEASES"
GH_DISPLAY=$(jq -nr --argjson count "$GH_COUNT" "$jq_format"'$count | format_downloads')
echo "Total downloads: $GH_DISPLAY"
echo
echo "Per release:"
echo "$GH_RAW" | jq -r "$jq_format"'.[] | "\n  \(.tag_name) (\(.published_at)):" as $header | $header, (.assets[] | select(.name | test("\\.(zsync|sha256)$|steam-compat") | not) | "    \(.name): \(.download_count | format_downloads)")'
echo

echo "--- Gitea (${GITEA_REPO}) ---"
GIT_RAW=$(curl -sfL "${GITEA_URL}/api/v1/repos/${GITEA_REPO}/releases?limit=50")
GIT_COUNT=$(echo "$GIT_RAW" | jq "$jq_total")
GIT_RELEASES=$(echo "$GIT_RAW" | jq 'length')
echo "Releases: $GIT_RELEASES"
GIT_DISPLAY=$(jq -nr --argjson count "$GIT_COUNT" "$jq_format"'$count | format_downloads')
echo "Total downloads: $GIT_DISPLAY"
echo
echo "Per release:"
echo "$GIT_RAW" | jq -r "$jq_format"'.[] | "\n  \(.tag_name) (\(.created_at)):" as $header | $header, (.assets[] | select(.name | test("\\.(zsync|sha256)$|steam-compat") | not) | "    \(.name): \(.download_count | format_downloads)")'
echo

TOTAL=$((GH_COUNT + GIT_COUNT))
BADGE_TOTAL=$(jq -nr --argjson total "$TOTAL" "$jq_format"'$total | format_downloads')
echo "========================"
echo "GitHub total:  $GH_DISPLAY"
echo "Gitea total:   $GIT_DISPLAY"
echo "Grand total:   $BADGE_TOTAL"
echo
echo "--- Top downloads (by file) ---"
jq_filter_top='[.[].assets[] | select(.name | test("\\.(zsync|sha256)$|steam-compat") | not)] | group_by(.name) | map({name: .[0].name, total: (map(.download_count) | add)}) | sort_by(-.total) | .[:15] | .[] | "  \(.total | format_downloads)\t\(.name)"'
echo "GitHub:"
echo "$GH_RAW" | jq -r "$jq_format $jq_filter_top"
echo
echo "Gitea:"
echo "$GIT_RAW" | jq -r "$jq_format $jq_filter_top"
echo
echo "--- Top downloads (by type) ---"
jq_type='[.[].assets[] | select(.name | test("\\.(zsync|sha256)$|steam-compat") | not)] | map({type: (.name | split(".") | last | if test("^AppImage$") then "AppImage" elif test("^deb$") then "deb" elif test("^rpm$") then "rpm" elif test("^zst$") then "pkg.tar.zst" else "other" end), downloads: .download_count}) | group_by(.type) | map({type: .[0].type, total: (map(.downloads) | add)}) | sort_by(-.total) | .[] | "  \(.type): \(.total | format_downloads)"'
echo "GitHub:"
echo "$GH_RAW" | jq -r "$jq_format $jq_type"
echo
echo "Gitea:"
echo "$GIT_RAW" | jq -r "$jq_format $jq_type"

if [[ "${CI:-}" != "true" ]]; then
    echo
    echo "Local run: README update and commit skipped"
    exit 0
fi

sed -i -E "s|-[0-9]+(\.[0-9]+)?k?-green\?style=flat-square|-$BADGE_TOTAL-green?style=flat-square|g" README.md README.ru.md
echo
echo "Badge updated: $BADGE_TOTAL"

git diff --quiet README.md README.ru.md && { echo "No changes to commit"; exit 0; }

timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

git config http.sslVerify false
git config --local user.email "gitea-actions@users.noreply.gitea.com"
git config --local user.name "Gitea Actions"

git add README.md README.ru.md
git commit -m "chore: download stats ${timestamp}"
remote_repo="https://${GITEA_ACTOR}:${GITEA_TOKEN}@${GITEA_SERVER}/${GITEA_REPOSITORY}.git"
git push "${remote_repo}" HEAD:main
echo "Pushed to Gitea"
