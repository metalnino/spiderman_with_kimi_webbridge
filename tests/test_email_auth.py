"""邮件网关 + 瑞达恒邮件验证码闭环（全离线：IMAP/SMTP/桥/DB 全部 mock，不发真信）。"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts import email_gateway as eg


class TestExtractCode(unittest.TestCase):
    def test_plain_six_digit(self):
        self.assertEqual(eg.extract_code("验证码 123456", ""), "123456")

    def test_four_digit_skip_year(self):
        self.assertEqual(eg.extract_code("我的验证码是 8842", ""), "8842")
        self.assertIsNone(eg.extract_code("今天是 2026-08-25", ""))

    def test_full_width_digits(self):
        self.assertEqual(eg.extract_code("验证码：８８４２６６"), "884266")

    def test_subject_and_body(self):
        self.assertEqual(eg.extract_code("Re: 【爬虫验证码】xx", "码是 556677"), "556677")

    def test_no_code(self):
        self.assertIsNone(eg.extract_code("收到，稍等"))


class TestGatewayFlow(unittest.TestCase):
    def test_send_no_credentials(self):
        with mock.patch.object(eg, "creds", return_value=("", "")):
            self.assertEqual(eg.send("a@b.c", "s", "b")["ok"], False)

    def test_send_ok_via_ssl(self):
        fake_smtp = mock.MagicMock()
        with mock.patch.object(eg, "creds", return_value=("u", "p")), \
             mock.patch.object(eg, "proxy", return_value=None), \
             mock.patch.object(eg.smtplib, "SMTP_SSL", return_value=fake_smtp):
            r = eg.send("to@x.com", "主题", "正文")
        self.assertTrue(r["ok"])
        fake_smtp.__enter__.return_value.login.assert_called_once_with("u", "p")

    def test_send_via_tunnel_when_proxy(self):
        fake_tunnel_smtp = mock.MagicMock()
        with mock.patch.object(eg, "creds", return_value=("u", "p")), \
             mock.patch.object(eg, "proxy", return_value="http://127.0.0.1:63009"), \
             mock.patch.object(eg, "_TunneledSMTP_SSL", return_value=fake_tunnel_smtp):
            r = eg.send("to@x.com", "主题", "正文")
        self.assertTrue(r["ok"])
        self.assertIn("proxy", r["host"])

    def test_poll_replies_filters_by_tag(self):
        from email.message import EmailMessage

        m1 = EmailMessage()
        m1["Subject"] = "【爬虫验证码】xx #rcv123"
        m1["From"] = "u@q.com"
        m1.set_content("123456")
        fake_imap = mock.MagicMock()
        fake_imap.search.return_value = ("OK", [b"1"])
        fake_imap.fetch.return_value = ("OK", [(b"1", m1.as_bytes())])
        with mock.patch.object(eg, "creds", return_value=("u", "p")), \
             mock.patch.object(eg, "proxy", return_value=None), \
             mock.patch.object(eg.imaplib, "IMAP4_SSL", return_value=fake_imap):
            replies = eg.poll_replies("#rcv123")
        self.assertEqual(len(replies), 1)
        self.assertEqual(eg.extract_code(replies[0]["body"]), "123456")

    def test_tunnel_socket_connect_handshake(self):
        fake_sock = mock.MagicMock()
        fake_sock.recv.side_effect = [b"HTTP/1.1 200 Connection Established\r\n\r\n"]
        with mock.patch.object(eg, "proxy", return_value="http://127.0.0.1:63009"), \
             mock.patch.object(eg.socket, "create_connection", return_value=fake_sock) as cc:
            raw = eg._tunnel_raw_socket("imap.gmail.com", 993)
        self.assertIs(raw, fake_sock)
        cc.assert_called_once_with(("127.0.0.1", 63009), timeout=30)
        fake_sock.sendall.assert_called_once()
        self.assertIn(b"CONNECT imap.gmail.com:993", fake_sock.sendall.call_args[0][0])

    def test_tunnel_socket_connect_rejected(self):
        fake_sock = mock.MagicMock()
        fake_sock.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\n"
        with mock.patch.object(eg, "proxy", return_value="http://127.0.0.1:63009"), \
             mock.patch.object(eg.socket, "create_connection", return_value=fake_sock):
            with self.assertRaises(RuntimeError):
                eg._tunnel_raw_socket("imap.gmail.com", 993)
        fake_sock.close.assert_called_once()

    def test_qq_provider_endpoints_and_creds(self):
        with mock.patch.object(eg, "provider", return_value="qq"), \
             mock.patch.object(eg, "qq_creds", return_value=("279152260@qq.com", "shouquanma")):
            self.assertEqual(eg._endpoints("qq")["smtp_host"], "smtp.qq.com")
            self.assertEqual(eg._endpoints("qq")["imap_port"], 993)
            # send 走 QQ 主机
            fake_smtp = mock.MagicMock()
            with mock.patch.object(eg.smtplib, "SMTP_SSL", return_value=fake_smtp) as smtp_mock, \
                 mock.patch.object(eg, "proxy", return_value=None):
                r = eg.send("to@x.com", "主题", "正文")
            self.assertTrue(r["ok"])
            self.assertEqual(smtp_mock.call_args[0][0], "smtp.qq.com")


class TestRccchinaEmailAuth(unittest.TestCase):
    def _mod(self):
        from scripts.jobs import rccchina_email_auth as ea

        return ea

    def test_auto_skips_without_credentials(self):
        ea = self._mod()
        with mock.patch.object(ea, "_creds_ready", return_value=False):
            r = ea.auto_if_needed("rccchina register_wall: x")
        self.assertTrue(r["skipped"])

    def test_auto_skips_without_wall(self):
        ea = self._mod()
        with mock.patch.object(ea, "_creds_ready", return_value=True):
            r = ea.auto_if_needed(None)
        self.assertTrue(r["skipped"])

    def test_auto_full_loop_success(self):
        ea = self._mod()
        req = {"ok": True, "tag": "rcv1"}
        comp = {"ok": True, "cookie_len": 42, "session_cookie_names": ["SESSION"], "closed_todos": 1}
        with mock.patch.object(ea, "_creds_ready", return_value=True), \
             mock.patch.object(ea, "_phone", return_value="13800000000"), \
             mock.patch.object(ea.Path, "exists", return_value=False), \
             mock.patch.object(ea, "request_code", return_value=req) as rc, \
             mock.patch.object(ea, "complete_login", side_effect=[{"ok": False, "error": "no_reply_yet"}, comp]) as cl, \
             mock.patch.object(ea.time, "sleep"):
            r = ea.auto("13800000000", "to@x.com", timeout_min=1, poll_sec=0)
        self.assertTrue(r["ok"])
        rc.assert_called_once()
        self.assertEqual(cl.call_count, 2)

    def test_complete_login_saves_cookie_and_closes_todo(self):
        ea = self._mod()
        marker = {"tag": "rcv1", "phone": "13800000000", "to": "to@x.com"}
        reply = {"uid": "9", "subject": f"Re: x {marker['tag']}", "body": "123456", "from": "u"}
        ck = {"ok": True, "cookie": "SESSION=abc; Hm_lvt_1=1",
              "cookies": [{"name": "SESSION"}, {"name": "Hm_lvt_1"}]}
        with mock.patch.object(ea.eg, "poll_replies", return_value=[reply]), \
             mock.patch.object(ea.eg, "mark_seen"), \
             mock.patch.object(ea.eg, "send", return_value={"ok": True}), \
             mock.patch.object(ea.time, "sleep"), \
             mock.patch.object(ea, "_bridge_status", return_value={"extensions": 1}), \
             mock.patch.object(ea.wb, "navigate", return_value={"ok": True}), \
             mock.patch.object(ea.wb, "export_cookies", return_value=ck), \
             mock.patch.object(ea, "_bridge_eval", return_value={"value": "欢迎，某某用户 退出"}), \
             mock.patch.object(ea.cookie_store, "save_cookie_header") as save, \
             mock.patch.object(ea, "list_open", return_value=[{"id": 7, "source_id": "rccchina"}]), \
             mock.patch.object(ea, "close_todo", return_value=True) as close, \
             mock.patch.object(ea, "MARKER", mock.MagicMock(exists=lambda: True)):
            r = ea.complete_login(marker)
        self.assertTrue(r["ok"])
        save.assert_called_once()
        close.assert_called_once_with(7, note=mock.ANY)

    def test_complete_login_reply_without_code_gives_up(self):
        ea = self._mod()
        marker = {"tag": "rcv1", "phone": "13800000000", "to": "to@x.com"}
        with mock.patch.object(ea.eg, "poll_replies", return_value=[
                {"uid": "1", "subject": "Re: x rcv1", "body": "好的收到", "from": "u"}]):
            r = ea.complete_login(marker)
        self.assertEqual(r["error"], "reply_without_code")


if __name__ == "__main__":
    unittest.main()
