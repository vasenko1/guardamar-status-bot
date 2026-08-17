#!/data/data/com.termux/files/usr/bin/sh

# POSIX-shell helpers for one project-scoped mkdir lock with stale-PID recovery.

acquire_runtime_lock() {
    runtime_lock_path=$1
    runtime_lock_owner="$runtime_lock_path/owner"
    if mkdir "$runtime_lock_path" 2>/dev/null; then
        printf '%s\n' "$$" >"$runtime_lock_owner"
        return 0
    fi

    runtime_lock_pid=
    if [ -f "$runtime_lock_owner" ]; then
        IFS= read -r runtime_lock_pid <"$runtime_lock_owner" || true
    fi
    case "$runtime_lock_pid" in
        ''|*[!0-9]*) ;;
        *)
            if kill -0 "$runtime_lock_pid" 2>/dev/null; then
                return 1
            fi
            ;;
    esac

    # The recorded owner no longer exists. Remove only this known one-file
    # project lock; an unexpected non-empty directory remains fail-closed.
    rm -f "$runtime_lock_owner"
    rmdir "$runtime_lock_path" 2>/dev/null || return 1
    mkdir "$runtime_lock_path" 2>/dev/null || return 1
    printf '%s\n' "$$" >"$runtime_lock_owner"
}

release_runtime_lock() {
    runtime_lock_path=$1
    runtime_lock_owner="$runtime_lock_path/owner"
    runtime_lock_pid=
    if [ -f "$runtime_lock_owner" ]; then
        IFS= read -r runtime_lock_pid <"$runtime_lock_owner" || true
    fi
    if [ "$runtime_lock_pid" != "$$" ]; then
        return 1
    fi
    rm -f "$runtime_lock_path/owner"
    rmdir "$runtime_lock_path" 2>/dev/null || true
}
