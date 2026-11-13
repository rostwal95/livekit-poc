"""Core cold imports and genuine opt-in native exports; no provider/PG workloads."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
import unittest


class PublicImportSurfaceTests(unittest.TestCase):
    def test_cold_core_exports_do_not_import_optional_sdks_or_start_io(self) -> None:
        script = textwrap.dedent(
            """
            import asyncio, hashlib, importlib.abc, json, socket, sys, threading
            from unittest.mock import patch
            import psycopg
            denied = []
            calls = {name:0 for name in ('connect','connect_ex','bind','listen','sendto','create_connection','thread','task','database')}
            class BlockOptionalSdk(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] in ('livekit','openai','anthropic','torch','transformers'):
                        denied.append(fullname)
                        raise RuntimeError('optional_sdk_forbidden')
                    return None
            def forbidden(name):
                def fail(*args, **kwargs):
                    calls[name] += 1
                    raise RuntimeError('import_io_forbidden')
                return fail
            assert not any(n.split('.')[0] in ('livekit','openai','anthropic','torch','transformers') for n in sys.modules)
            blocker = BlockOptionalSdk()
            sys.meta_path.insert(0, blocker)
            with patch.object(socket.socket,'connect',forbidden('connect')), patch.object(socket.socket,'connect_ex',forbidden('connect_ex')), patch.object(socket.socket,'bind',forbidden('bind')), patch.object(socket.socket,'listen',forbidden('listen')), patch.object(socket.socket,'sendto',forbidden('sendto')), patch.object(socket,'create_connection',forbidden('create_connection')), patch.object(threading.Thread,'start',forbidden('thread')), patch.object(asyncio,'create_task',forbidden('task')), patch.object(psycopg,'connect',forbidden('database')):
                import delegation_reliability as public
                import delegation_reliability.contracts
                import delegation_reliability.coordinator as coordinator
                import delegation_reliability.channel_policy_contracts
                import delegation_reliability.channel_policy_execution as channel
                import delegation_reliability.completion as completion
                lazy = {'run_baseline','NativePolicyAgent','NativePolicyApplication','NativePolicyError','NativePolicyObservation','encode_native_policy_observation','parse_native_policy_observation'}
                assert not lazy.intersection(vars(public))
                for name in public.__all__:
                    if name not in lazy:
                        getattr(public,name)
                assert public.ChannelPolicyCoordinator is channel.ChannelPolicyCoordinator
                assert public.DelegationCoordinator is coordinator.DelegationCoordinator
                assert public.ChannelPolicyDeliveryClient is completion.ChannelPolicyDeliveryClient
                assert len(public.__all__)==121 and len(set(public.__all__))==121
                assert hashlib.sha256(json.dumps(public.__all__,separators=(',',':')).encode()).hexdigest()=='c2d62843514ff31d802e37d468db1e328066436984a3403bd92ca1a9c9a16ffa'
                assert set(public.__all__).union({'baseline','scripted','native_policy'}).issubset(dir(public))
                assert not denied and not any(calls.values())
                try:
                    getattr(public,'not_a_public_export')
                except AttributeError:
                    pass
                else:
                    raise AssertionError('unknown_attribute_accepted')
                assert not denied
                for name in ('NativePolicyAgent','run_baseline','scripted'):
                    try:
                        getattr(public,name)
                    except RuntimeError as error:
                        assert str(error)=='optional_sdk_forbidden'
                    else:
                        raise AssertionError('native_export_was_a_substitute')
                    assert name not in vars(public)
                    assert public.ChannelPolicyCoordinator is channel.ChannelPolicyCoordinator
                assert len(denied)>=3
                assert not any(calls.values())
                assert not any(name in sys.modules for name in ('delegation_reliability.baseline','delegation_reliability.scripted','delegation_reliability.native_policy'))
            print(json.dumps({'status':'passed','core_exports':114,'blocked_explicit_sdk_paths':len(denied),'io_attempts':calls},sort_keys=True))
            """
        )
        environment = {
            "PATH": os.defpath,
            "LANG": "en_US.UTF-8",
            "CI": "1",
            "NO_COLOR": "1",
        }
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertEqual(observed["status"], "passed")
        self.assertEqual(observed["core_exports"], 114)
        self.assertFalse(any(observed["io_attempts"].values()))

    def test_explicit_native_exports_preserve_real_identity_and_signatures(self) -> None:
        from livekit.agents import Agent

        import delegation_reliability as public

        baseline = importlib.import_module("delegation_reliability.baseline")
        native = importlib.import_module("delegation_reliability.native_policy")
        for name, module in (
            ("run_baseline", baseline),
            ("NativePolicyAgent", native),
            ("NativePolicyApplication", native),
            ("NativePolicyError", native),
            ("NativePolicyObservation", native),
            ("encode_native_policy_observation", native),
            ("parse_native_policy_observation", native),
        ):
            with self.subTest(export=name):
                actual = getattr(public, name)
                original = getattr(module, name)
                self.assertIs(actual, original)
                self.assertIs(getattr(public, name), original)
                self.assertIs(vars(public)[name], original)
                self.assertEqual(inspect.signature(actual), inspect.signature(original))
                self.assertEqual(actual.__module__, module.__name__)
        self.assertTrue(issubclass(public.NativePolicyAgent, Agent))
        self.assertTrue(inspect.iscoroutinefunction(public.run_baseline))

    def test_module_aliases_and_ordered_wildcard_api_remain_compatible(self) -> None:
        import delegation_reliability as public
        from delegation_reliability import baseline, native_policy, scripted

        for name, module in (
            ("baseline", baseline),
            ("native_policy", native_policy),
            ("scripted", scripted),
        ):
            with self.subTest(module=name):
                self.assertIs(getattr(public, name), module)
                self.assertIs(module, importlib.import_module("delegation_reliability." + name))
        # The pre-change ordered public API is a compatibility contract, not a new export list.
        self.assertEqual(len(public.__all__), 121)
        self.assertEqual(len(set(public.__all__)), 121)
        self.assertEqual(
            hashlib.sha256(json.dumps(public.__all__, separators=(",", ":")).encode()).hexdigest(),
            "c2d62843514ff31d802e37d468db1e328066436984a3403bd92ca1a9c9a16ffa",
        )
        wildcard = __import__("delegation_reliability", fromlist=("*",))
        self.assertIs(wildcard, public)
        for name in public.__all__:
            self.assertIs(getattr(wildcard, name), getattr(public, name))
