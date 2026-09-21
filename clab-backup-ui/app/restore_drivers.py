"""The platform contract of *Replace running configuration*.

:mod:`restore` orchestrates a restore (backups, job state, reconnect, verification) and knows no
NOS command. Everything a platform decides lives in its driver module, and this registry maps a
node's kind to it. A driver provides:

``SUPPORTED_KINDS``
    The containerlab kinds it was proven on.
``validate_candidate(text)``
    Refuse a candidate that is empty, of another format or visibly truncated, before any device is
    touched. Raises :class:`restore_shell.RestoreError`.
``apply_candidate(client, candidate, confirm_minutes, **options) -> dict``
    Replace the whole active configuration with the candidate inside the NOS's own transaction and
    activate it with the NOS's own timed recovery (Junos ``commit confirmed``, EOS
    ``commit timer``, IOS XR ``commit replace confirmed``). Returns ``diff`` (the device's own review
    diff), ``no_op`` and ``handle``: whatever a later confirmation on a *fresh* connection needs.
``confirm(client, handle, **options) -> dict``
    Cancel the timed recovery and make the configuration persistent where the NOS does not do that
    by itself. Must never confirm somebody else's pending change.
``pending(client, **options)``
    Truthy while a timed change awaits confirmation on the node (used to reconcile a restore that
    lost its session or its manager).
``HOLDS_SESSION`` and ``release(token)`` (optional)
    For a NOS where only the CLI session that armed a timed change can confirm it (IOS XR). After a
    successful ``apply_candidate`` the driver then owns the connection it was given and keeps it,
    under the job token, in the manager's memory; the service does not close it. ``confirm`` still
    receives a *fresh* connection, which is the proof that management survived, and only then sends
    the confirmation on the held session. ``release(token)`` ends a held session without
    confirming, and the service always calls it when the node is settled. It leaves the node's
    configuration mode cleanly first, so no session of the manager lingers and blocks the next
    restore; on IOS XR leaving the arming session while its change is still unconfirmed makes the
    node undo the change at once instead of at the timer's expiry, which is what giving up means.
    A manager restart loses held sessions: the node rolls back at its timer and the read-back
    reports it. A driver must never confirm before the fresh connection exists.
``blocked(client, **options) -> str`` (optional)
    A student-readable reason why a restore must not start now although nothing is pending (Junos:
    somebody's uncommitted edits in the shared candidate), or ''. Asked at the review step; the
    driver refuses by itself at apply time too.
``cleanup(client, **options)`` (optional)
    Remove what the manager's own dead session left on the node (EOS: an uncommitted session under
    the manager's name). Never anything of another name.
``persist(client, **options) -> bool`` (optional)
    Make the active configuration the startup configuration where a commit does not (EOS).
``capture(client, **options) -> str``
    The active configuration in the platform's comparable form.
``compare(desired, actual) -> (missing, extra)``
    Desired-state comparison in that form. Exclusions are listed beside each implementation and in
    docs/multi-platform-restore/README.md; nothing else is tolerated.

Drivers reach a node only over the manager's direct node-SSH path. No host helper is involved.
"""
from . import restore_eos, restore_iosxr, restore_junos

DRIVERS = (restore_junos, restore_eos, restore_iosxr)


def for_platform(platform):
    return next((driver for driver in DRIVERS if platform in driver.SUPPORTED_KINDS), None)


def supported_kinds():
    return tuple(kind for driver in DRIVERS for kind in driver.SUPPORTED_KINDS)


def options(driver, creds):
    """Per-connection keyword arguments a driver understands (the EOS enable password)."""
    if driver is restore_eos:
        return {'enable_password': (creds or {}).get('enable_password') or ''}
    return {}
