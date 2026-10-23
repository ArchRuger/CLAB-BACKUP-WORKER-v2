"""The pure telnet codec and the gate helpers of the serial console (docs/parity-campaign/C04-DESIGN.md §2.4)."""
import time
import unittest

from app.node_console import (ACCEPT_DO, ACCEPT_WILL, BINARY, DO, DONT, ECHO, IAC, SB, SE, SGA, TelnetCodec, WILL, WONT,
                              container_age, health_part, telnet_escape)

# What qemu's telnet chardev sends at once on a free console (verified live): WILL ECHO, WILL SGA, WILL BINARY, DO BINARY.
NEGOTIATION = bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, WILL, BINARY, IAC, DO, BINARY])
REPLIES = bytes([IAC, DO, ECHO, IAC, DO, SGA, IAC, DO, BINARY, IAC, WILL, BINARY])


class CodecTests(unittest.TestCase):
    def test_the_live_negotiation_produces_no_output_and_exactly_the_four_answers(self):
        self.assertEqual(TelnetCodec().feed(NEGOTIATION), (b'', REPLIES))
        self.assertEqual(ACCEPT_WILL, {ECHO, SGA, BINARY}); self.assertEqual(ACCEPT_DO, {BINARY})

    def test_plain_bytes_pass_untouched_including_the_devices_own_escape_sequences(self):
        data = b'\x1b[2J\r\nlogin: \x07'
        self.assertEqual(TelnetCodec().feed(data), (data, b''))

    def test_doubled_iac_is_one_literal_0xff(self):
        self.assertEqual(TelnetCodec().feed(b'a\xff\xffb'), (b'a\xffb', b''))

    def test_a_sequence_split_across_chunks_keeps_its_state(self):
        codec = TelnetCodec()
        self.assertEqual(codec.feed(b'ab\xff'), (b'ab', b''))
        self.assertEqual(codec.feed(b'\xfb\x01cd'), (b'cd', bytes([IAC, DO, ECHO])))
        codec = TelnetCodec()
        self.assertEqual(codec.feed(b'\xff\xfb'), (b'', b''))
        self.assertEqual(codec.feed(b'\x03x'), (b'x', bytes([IAC, DO, SGA])))
        codec = TelnetCodec()
        self.assertEqual(codec.feed(b'\xff'), (b'', b''))
        self.assertEqual(codec.feed(b'\xffy'), (b'\xffy', b''))

    def test_subnegotiation_is_dropped_whole_across_chunks(self):
        codec = TelnetCodec()
        self.assertEqual(codec.feed(b'a' + bytes([IAC, SB, 31, 0, 80])), (b'a', b''))
        self.assertEqual(codec.feed(bytes([0, 24, IAC]) + b''), (b'', b''))
        self.assertEqual(codec.feed(bytes([SE]) + b'b'), (b'b', b''))
        # An escaped 0xFF inside the subnegotiation does not end it.
        codec = TelnetCodec()
        self.assertEqual(codec.feed(bytes([IAC, SB, 31, IAC, IAC, 5, IAC, SE]) + b'z'), (b'z', b''))

    def test_other_options_are_refused_once_and_a_repeat_is_not_answered_again(self):
        codec = TelnetCodec()
        self.assertEqual(codec.feed(bytes([IAC, WILL, 24])), (b'', bytes([IAC, DONT, 24])))
        self.assertEqual(codec.feed(bytes([IAC, WILL, 24])), (b'', b''))
        self.assertEqual(codec.feed(bytes([IAC, DO, 24])), (b'', bytes([IAC, WONT, 24])))
        self.assertEqual(codec.feed(bytes([IAC, DO, 24])), (b'', b''))
        self.assertEqual(codec.feed(bytes([IAC, DO, ECHO])), (b'', bytes([IAC, WONT, ECHO])))
        # A repeated WILL ECHO after the live negotiation is not answered a second time.
        codec = TelnetCodec(); codec.feed(NEGOTIATION)
        self.assertEqual(codec.feed(bytes([IAC, WILL, ECHO]) + b'x'), (b'x', b''))

    def test_wont_dont_and_other_two_byte_commands_are_dropped_without_a_reply(self):
        codec = TelnetCodec()
        self.assertEqual(codec.feed(bytes([IAC, WONT, ECHO, IAC, DONT, BINARY])), (b'', b''))
        self.assertEqual(codec.feed(bytes([IAC, 241]) + b'ok' + bytes([IAC, 249])), (b'ok', b''))   # NOP and GA

    def test_telnet_escape_doubles_0xff_and_leaves_utf8_alone(self):
        self.assertEqual(telnet_escape(b'a\xffb'), b'a\xff\xffb')
        self.assertEqual(telnet_escape('ÿ€'.encode()), 'ÿ€'.encode())
        self.assertEqual(telnet_escape(b'admin\r'), b'admin\r')
        self.assertNotIn(0xff, 'ÿ'.encode())


class GateHelperTests(unittest.TestCase):
    def test_health_part_reads_dockers_status_line(self):
        self.assertEqual(health_part('Up 12 minutes (health: starting)'), 'starting')
        self.assertEqual(health_part('Up 23 minutes (unhealthy)'), 'unhealthy')
        self.assertEqual(health_part('Up 2 hours (healthy)'), 'healthy')
        for status in ('Up 2 hours', 'Exited (0) 3 minutes ago', '', None):
            self.assertEqual(health_part(status), '', status)

    def test_container_age_adds_the_time_since_the_inspection_and_is_none_for_coarse_uptimes(self):
        now = time.time()
        self.assertEqual(container_age('Up 30 seconds', now - 10, now), 40)
        self.assertEqual(container_age('Up 30 seconds', now - 200, now), 230)
        self.assertEqual(container_age('Up About a minute (healthy)', now, now), 60)
        self.assertEqual(container_age('Up 30 seconds', now + 50, now), 30, 'a clock that went backwards never makes the container younger')
        self.assertIsNone(container_age('Up 2 hours (healthy)', now, now))
        self.assertIsNone(container_age('', now, now))


if __name__ == '__main__':
    unittest.main()
