"""Verify failed or cancelled sends never leave a subprocess running or retry."""

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import api


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def sleeper(self):
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(5)",
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

    async def test_timeout_reaps_process_and_reports_unknown_delivery(self):
        process = await self.sleeper()
        with patch.object(
            api.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ) as launch:
            with self.assertRaises(HTTPException) as error:
                await api.run_wacli("send", "text", sending=True, timeout=0.01)
        self.assertEqual(error.exception.status_code, 504)
        self.assertIn("Delivery is unknown", error.exception.detail)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(launch.await_count, 1)

    async def test_cancelled_request_reaps_process(self):
        process = await self.sleeper()
        with patch.object(
            api.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            request = asyncio.create_task(api.run_wacli("send", "text", sending=True))
            await asyncio.sleep(0.01)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
        self.assertIsNotNone(process.returncode)

    async def test_malformed_cli_response_becomes_upstream_error(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "print('[]')",
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        with patch.object(
            api.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)
        ):
            with self.assertRaises(HTTPException) as error:
                await api.run_wacli("auth", "status")
        self.assertEqual(error.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
