#!/usr/bin/env bash
set -euo pipefail

COMMENTS=(
  "Refine IBM MQ exporter metric collection behavior"
  "Update queue and channel discovery for exporter"
  "Improve Prometheus output labels for MQ metrics"
  "Harden reconnection flow for queue manager outages"
  "Tune MQ statistics and accounting queue processing"
  "Adjust exporter configuration defaults for lab"
  "Improve PCF query handling and parser resilience"
  "Refine channel status metric normalization"
  "Update queue depth and throughput metric mapping"
  "Improve z/OS metric extraction logic"
  "Tighten resource monitor metric collection paths"
  "Refine subscription and topic metric coverage"
  "Improve exporter logging and diagnostics output"
  "Polish build and packaging workflow for exporter"
  "Update CMake and dependency configuration"
  "Refine Docker image build pipeline for MQ lab"
  "Improve remote exporter startup and target mapping"
  "Update embedded exporter setup for qm3 container"
  "Refine docker_build automation for fixed qm topology"
  "Align lab scripts with qm1 qm2 qm3 deployment model"
  "Improve Prometheus scrape configuration workflow"
  "Update Prometheus integration for multi-endpoint scrape"
  "Refine mq-monitoring image initialization behavior"
  "Improve MQSC bootstrap commands for lab containers"
  "Update exporter service registration for MQ runtime"
  "Refine IBM MQ channel auth and permission setup"
  "Improve repo automation script reliability"
  "Polish push helper workflow and commit automation"
  "Update README deployment and operations guidance"
  "Refine technical documentation for lab architecture"
  "Improve troubleshooting guidance for MQ exporter"
  "Update metrics catalog and label documentation"
  "Refine CLI usage and config documentation"
  "Improve .gitignore coverage and section clarity"
  "General maintenance pass for IBM MQ metrics exporter repo"
  "Stabilize current IBM MQ metrics exporter changes"
  "Checkpoint current mq exporter implementation state"
  "Publish latest updates for ibmmq metrics exporter"
  "Sync current docker and metrics workflow refinements"
  "Commit current exporter code and lab integration updates"
)

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  printf '%s [push-it] %s\n' "$(timestamp)" "$*"
}

require_clean_repo_context() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "ERROR: this script must be run inside the repository."
    exit 1
  fi
}

current_branch() {
  git symbolic-ref --quiet --short HEAD
}

collector_dirty() {
  if [ -n "$(git status --porcelain)" ]; then
    printf 'true\n'
  else
    printf 'false\n'
  fi
}

log_collector_dirty() {
  local dirty
  dirty="$(collector_dirty)"
  log "collector_dirty=${dirty}"
  if [ "${dirty}" = "true" ]; then
    log "Builds made now will be stamped dirty=true because local changes are not committed yet."
  else
    log "Builds made now will be stamped dirty=false because the working tree is clean."
  fi
}

pick_comment() {
  local count index
  count="${#COMMENTS[@]}"
  index="$(od -An -N4 -tu4 /dev/urandom | tr -d ' ')"
  printf '%s\n' "${COMMENTS[$((index % count))]}"
}

require_clean_repo_context

branch="$(current_branch)"
if [ -z "${branch}" ]; then
  log "ERROR: detached HEAD; checkout a branch before pushing."
  exit 1
fi

commit_message="${1:-$(pick_comment)}"

log "Checking repository build-stamp state before commit."
log_collector_dirty

log "Staging local changes."
git add -A

if git diff --cached --quiet; then
  log "No staged changes to commit."
else
  log "Committing with message: ${commit_message}"
  git commit -m "${commit_message}"
fi

log "Checking repository build-stamp state after commit."
log_collector_dirty

if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
  log "Pushing ${branch} to ${upstream}."
  git push
else
  log "No upstream configured; pushing ${branch} to origin and setting upstream."
  git push -u origin "${branch}"
fi
