"""No probe cleanup may discard a name substituted after its ownership check."""

import os

from harness import publication_fs as fs


def test_probe_name_substitution_cannot_destroy_unmanaged_inode(tmp_path, monkeypatch):
    source = tmp_path / 'operator-source'
    source.write_bytes(b'unmanaged probe boundary bytes')
    inode = source.stat().st_ino
    root_fd = fs.open_directory(tmp_path)
    real_stat, real_sync = os.stat, fs.sync_directory
    ready = False
    injected = False

    def synced(fd):
        nonlocal ready
        real_sync(fd)
        ready = True

    def checked_then_substituted(name, *args, **kwargs):
        nonlocal injected
        result = real_stat(name, *args, **kwargs)
        if (ready and not injected and isinstance(name, str) and name.startswith('.cap-')
                and kwargs.get('dir_fd') is not None):
            injected = True
            os.rename('operator-source', name, src_dir_fd=root_fd, dst_dir_fd=kwargs['dir_fd'])
        return result

    monkeypatch.setattr(fs, 'sync_directory', synced)
    monkeypatch.setattr(os, 'stat', checked_then_substituted)
    try:
        try:
            fs.check_capabilities(root_fd)
        except OSError:
            pass  # Conflict refusal allowed; deleting unmanaged bytes never allowed.
        assert injected, 'real post-sync name observation must exercise substitution window'
        kept = [path for path in tmp_path.rglob('*') if path.is_file() and path.stat().st_ino == inode]
        assert len(kept) == 1, 'cleanup discarded only unmanaged inode name'
        assert kept[0].read_bytes() == b'unmanaged probe boundary bytes'
    finally:
        os.close(root_fd)
