"""Check sshd's effective account policy before reloading the service."""
import sys

EXPECTED = {
    'authenticationmethods': 'password',
    'passwordauthentication': 'yes',
    'kbdinteractiveauthentication': 'no',
    'pubkeyauthentication': 'no',
    'permitemptypasswords': 'no',
    'forcecommand': '/usr/local/sbin/clab-manager-gateway',
    'disableforwarding': 'yes',
    'permittty': 'no',
    'permittunnel': 'no',
    'permituserrc': 'no',
    'permituserenvironment': 'no',
}

if __name__ == '__main__':
    actual = dict(line.strip().split(None, 1) for line in sys.stdin if len(line.split()) > 1)
    if any(actual.get(key) != value for key, value in EXPECTED.items()):
        sys.exit('Conflicting SSH account policy. Review earlier Match rules for clab-discovery; configuration was not applied.')
