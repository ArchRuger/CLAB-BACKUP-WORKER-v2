#!/usr/bin/env bash
# Register Ben's existing HTTPS checkout, or refresh installed code without relinking.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
owner=''; repo=''; remote=origin; prefix=''; label=''; refresh=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner|--repo|--remote|--prefix|--label)
      [[ $# -ge 2 ]] || exit 64
      case "$1" in
        --owner) owner=$2;; --repo) repo=$2;; --remote) remote=$2;; --prefix) prefix=$2;; --label) label=$2;;
      esac
      shift 2;;
    --refresh) refresh=true; shift;;
    *) echo 'Options: --owner USER --repo /absolute/checkout [--remote origin] [--prefix labs/bgp] [--label NAME], or --refresh.' >&2; exit 64;;
  esac
done
if ! $refresh; then
  [[ -n "$owner" && -n "$repo" ]] || { echo 'Supply --owner and --repo, or use --refresh to retain all bindings.' >&2; exit 64; }
elif [[ -n "$owner" || -n "$repo" || -n "$prefix" || -n "$label" || "$remote" != origin ]]; then
  echo '--refresh cannot change repository settings.' >&2; exit 64
fi
[[ -f /etc/ssh/clab-manager-password.conf ]] || { echo 'Run setup-discovery.sh first.' >&2; exit 1; }
[[ -x /usr/bin/git && -x /usr/bin/python3 ]] || { echo 'Install git and python3 first.' >&2; exit 1; }
for path in /etc/clab-manager /etc/clab-manager/git.json /usr/local/lib/clab-manager /usr/local/lib/clab-manager/host_git.py /usr/local/sbin/clab-manager-git /usr/local/sbin/clab-manager-gateway /etc/sudoers.d/clab-manager-git; do
  [[ ! -L "$path" ]] || { echo 'Refusing a symlink at a helper installation path.' >&2; exit 1; }
done
install -d -o root -g root -m 0700 /etc/clab-manager
install -d -o root -g root -m 0755 /usr/local/lib/clab-manager
install -o root -g root -m 0644 "$script_dir/../clab-backup-ui/app/host_git.py" /usr/local/lib/clab-manager/host_git.py
install -o root -g root -m 0755 "$script_dir/clab-manager-gateway" /usr/local/sbin/clab-manager-gateway
temp_dir=$(mktemp -d)
trap 'rm -f -- "$temp_dir/helper" "$temp_dir/sudoers"; rmdir -- "$temp_dir"' EXIT
cat > "$temp_dir/helper" <<'SH'
#!/bin/sh
set -eu
[ "$#" -eq 0 ] || exit 64
cd /
exec /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root /usr/bin/python3 -I /usr/local/lib/clab-manager/host_git.py
SH
printf '%s\n' 'clab-discovery ALL=(root) NOPASSWD: /usr/local/sbin/clab-manager-git ""' > "$temp_dir/sudoers"
visudo -cf "$temp_dir/sudoers"
install -o root -g root -m 0755 "$temp_dir/helper" /usr/local/sbin/clab-manager-git
install -o root -g root -m 0440 "$temp_dir/sudoers" /etc/sudoers.d/clab-manager-git
/usr/bin/python3 -I - "$refresh" "$owner" "$repo" "$remote" "$prefix" "$label" <<'PY'
import importlib.util, json, os, pathlib, pwd, re, sys, uuid
spec=importlib.util.spec_from_file_location('host_git','/usr/local/lib/clab-manager/host_git.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.root_file(pathlib.Path(h.GIT))
registry=h.load_registry() if h.REGISTRY.exists() else {'repositories':[]}
if sys.argv[1]=='true':
    if not h.REGISTRY.exists(): h.atomic_json(h.REGISTRY,registry)
    print('Git helper refreshed; all registered repositories retained.')
    sys.exit(0)
owner,repo,remote,prefix,label=sys.argv[2:]
try:
    account=pwd.getpwnam(owner)
    if account.pw_uid==0 or owner=='clab-discovery': raise ValueError('Choose the ordinary VM account that owns and authenticates this Git checkout.')
    path=pathlib.Path(repo)
    if not path.is_absolute() or '..' in path.parts or str(path)=='/': raise ValueError('Supply the absolute checkout root.')
    prefix=h.relpath(prefix,empty=True)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',remote): raise ValueError('Use a literal remote name.')
    label=label or path.name
    if len(label)>100 or any(ord(c)<32 for c in label): raise ValueError('Use a short repository label.')
    old=next((b for b in registry['repositories'] if b['path']==str(path) and b['prefix']==prefix),None)
    for b in registry['repositories']:
        if b is old or b['path']!=str(path): continue
        p=b['prefix']
        if not prefix or not p or prefix.startswith(p+'/') or p.startswith(prefix+'/'): raise ValueError('Managed prefixes in the same repository must not overlap.')
    binding={'id':old['id'] if old else uuid.uuid4().hex,'label':label,'owner':owner,'uid':account.pw_uid,'gid':account.pw_gid,
             'home':account.pw_dir,'path':str(path),'remote':remote,'prefix':prefix,'branch':'','push_url':'','revision':''}
    # Root reads only the registry/account database. The child opens the repository
    # and invokes every Git/config/credential/hook command after a permanent drop.
    read_fd,write_fd=os.pipe();pid=os.fork()
    if pid==0:
        os.close(read_fd)
        try:
            h.drop_owner(binding)
            worker=h.GitRepository(binding)
            if worker.root.stat().st_uid!=account.pw_uid or worker.control.stat().st_uid!=account.pw_uid: raise ValueError('The checkout and .git must be owned by the registered account.')
            binding['branch']=worker.run('symbolic-ref','--quiet','--short','HEAD')
            worker.run('check-ref-format','--branch',binding['branch'])
            urls=worker.run('remote','get-url','--push','--all',remote).splitlines()
            if len(urls)!=1: raise ValueError('Configure exactly one HTTPS push URL.')
            binding['push_url']=h.checked_url(urls[0])
            binding['anchor']=worker.validate();worker.clean()
            if worker.remote_head()!=binding['anchor']: raise ValueError('Before linking, synchronize the current branch with its existing remote branch using your ordinary Git login.')
            binding['revision']=h.digest({k:v for k,v in binding.items() if k!='revision'})
            result={'binding':binding}
        except ValueError as error: result={'error':str(error)}
        except Exception: result={'error':'Could not register the repository. Check checkout permissions and the owner\'s HTTPS Git authentication.'}
        with os.fdopen(write_fd,'w') as stream: json.dump(result,stream)
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as stream: raw=stream.read(16385)
    os.waitpid(pid,0)
    if len(raw)>16384: raise ValueError('Unexpected registration response.')
    result=json.loads(raw)
    if 'error' in result: raise ValueError(result['error'])
    binding=result['binding']
    registry['repositories']=[b for b in registry['repositories'] if b['id']!=binding['id']]+[binding]
    h.atomic_json(h.REGISTRY,registry)
    print('Registered '+binding['label']+' on '+binding['branch']+'. Binding ID: '+binding['id'])
except (ValueError, KeyError) as error:
    sys.exit(str(error))
PY
echo 'Git login remains with the repository owner. Select the repository under More > Git repository in the manager.'
