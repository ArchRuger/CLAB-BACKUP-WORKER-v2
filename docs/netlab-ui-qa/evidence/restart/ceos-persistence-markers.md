# cEOS persistence markers around a product-driven Restart device (final build, 15:16-15:17 UTC)

## set (Loopback99 description saved with write memory; Loopback98 description in running config only)
ceos(config)#interface Loopback99
ceos(config-if-Lo99)#description restart-saved-marker
ceos#write memory
Copy completed successfully.
ceos(config)#interface Loopback98
ceos(config-if-Lo98)#description restart-unsaved-marker

## before the restart (nodecli.py, independent read-back)
show running-config | include marker
   description restart-unsaved-marker
   description restart-saved-marker
ceos#show startup-config | include marker
   description restart-saved-marker
SAVED marker present: True
UNSAVED marker present: True

## after the restart (job: 26 checks, 0 failed; record in docs/netlab-ui-qa/evidence/restart)
show running-config | include marker
   description restart-saved-marker
ceos#show startup-config | include marker
   description restart-saved-marker
SAVED marker present: True
UNSAVED marker present: False
