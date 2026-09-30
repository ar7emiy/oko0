"""Validate Spark v2 without changing notebook settings or running production inputs.

    python verify_spark_v2.py           # memory regressions + comparison parity
    python verify_spark_v2.py --full    # all embedded B1 tests (Spark/fork tests skip locally)

This runner exercises the disk-backed reference path. It does not start Spark or
claim to validate Databricks scheduling, Unity Catalog access, or Delta writes.
Enable RUN_SELF_TESTS in the notebook on a small synthetic cluster run for those.
"""
import ast
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE / "goko_record_linkage_mvp_b1_spark_v2.ipynb"


def load_definitions():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf8"))
    sources = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    original = json.loads((HERE / 'goko_record_linkage_mvp_b1.ipynb').read_text(encoding='utf8'))
    def core_cells(book):
        return [''.join(c['source']) for c in book['cells'] if c['cell_type'] == 'code'
                and ''.join(c['source']).startswith('# ---- Matching core')]
    if core_cells(original) != core_cells(notebook):
        raise AssertionError('v2 matching core differs from the supplied pandas source')
    for index, source in enumerate(sources):
        ast.parse("\n".join(line for line in source.splitlines() if not line.startswith("%")),
                  filename=f"{NOTEBOOK.name}:code_cell_{index}")
    namespace = {"__name__": "spark_v2_validation", "__file__": str(NOTEBOOK)}
    import types
    module = types.ModuleType(namespace["__name__"])
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    namespace["__file__"] = str(NOTEBOOK)
    definitions = True
    for source in sources:
        if source.startswith("# ---- Settings:"):
            definitions = False
        if source.startswith("# Libraries"):
            continue
        if source.startswith("# ---- Spark: the same tasks"):
            # Spark APIs are imported only on the cluster; definitions below remain parseable.
            source = source.replace("from pyspark.broadcast import Broadcast", "class Broadcast: pass")
            source = source.replace("from pyspark import cloudpickle as _cloudpickle", "import cloudpickle as _cloudpickle")
        if definitions or source.startswith("import unittest, tempfile, io"):
            exec(compile(source, str(NOTEBOOK), "exec"), namespace)
    return namespace


def pool_suite(namespace):
    # Enforce one collect per bounded wave, lazy consumption and broadcast cleanup.
    # This transport harness does not stand in for a real Spark integration test.
    exec("def _pool_task(t):\n    if t < 0: raise ValueError('injected task failure')\n    return t * _SHARED['factor'][0], _IN_WORKER and (_SHARED['factor'] is _SHARED.get('alias', _SHARED['factor']))\n", namespace)

    class FakeBroadcast:
        def __init__(self, value):
            self.value, self.destroyed = value, False
        def destroy(self, blocking=False):
            self.destroyed = True

    class FakeRDD:
        def __init__(self, data, context, fn=None):
            self.data, self.context, self.fn = data, context, fn
        def mapPartitions(self, fn):
            return FakeRDD(self.data, self.context, fn)
        def toLocalIterator(self, prefetchPartitions=False):
            raise AssertionError('partition-by-partition dispatch would serialize the wave')
        def collect(self):
            self.context.collect_calls += 1
            result = []
            for group in self.data:
                fn = namespace['_cloudpickle'].loads(namespace['_cloudpickle'].dumps(self.fn))
                result.extend(fn(iter([group])))
            return result[:-1] if self.context.drop_result else result

    class FakeContext:
        defaultParallelism = 12
        def __init__(self):
            self.broadcasts, self.waves = [], []
            self.collect_calls, self.drop_result = 0, False
            self.properties = {'spark.job.description': 'original description'}
        def getLocalProperty(self, key):
            return self.properties.get(key)
        def setLocalProperty(self, key, value):
            self.properties[key] = value
        def setJobDescription(self, description):
            self.setLocalProperty('spark.job.description', description)
        def broadcast(self, value):
            item = FakeBroadcast(value)
            self.broadcasts.append(item)
            return item
        def parallelize(self, data, partitions):
            if partitions != len(data):
                raise AssertionError('expected one group per partition')
            self.waves.append(data)
            return FakeRDD(data, self)

    class PoolTests(unittest.TestCase):
        def test_waves_order_single_task_and_broadcast_cleanup(self):
            from types import SimpleNamespace
            context = FakeContext()
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context), executor_processes=2, progress=False)
            pool.executors = lambda: 3
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                factor = [7]
                result = pool.map(namespace['_pool_task'], range(19), {'factor': factor, 'alias': factor})
                self.assertEqual(result, [(i*7, True) for i in range(19)])
                self.assertTrue(all(len(g) <= 2 for wave in context.waves for g in wave))
                self.assertTrue(all(sum(map(len, wave)) <= 6 for wave in context.waves))
                self.assertEqual(context.collect_calls, 4)  # 19 tasks / 6 per wave
                self.assertEqual(pool.last_call['tasks'], 19)
                self.assertEqual(pool.last_call['waves'], 4)
                self.assertEqual(pool.map(namespace['_pool_task'], [3], {'factor': [2]}), [(6, True)])
            self.assertEqual(context.collect_calls, 5)
            self.assertEqual(context.properties['spark.job.description'], 'original description')
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))

        def test_exception_releases_broadcasts(self):
            from types import SimpleNamespace
            context = FakeContext()
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context), progress=False)
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                with self.assertRaises(ValueError):
                    pool.map(namespace['_pool_task'], [-1], {'factor': [3]})
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))
            self.assertEqual(context.properties['spark.job.description'], 'original description')

        def test_next_wave_waits_for_consumption_and_close_releases_inputs(self):
            from types import SimpleNamespace
            context = FakeContext()
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context), executor_processes=2, progress=False)
            pool.executors = lambda: 3
            consumed = []
            def tasks():
                for task in range(19):
                    consumed.append(task)
                    yield task
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                results = pool.iter_map(namespace['_pool_task'], tasks(), {'factor': [7]})
                self.assertEqual(next(results), (0, True))
                self.assertEqual(consumed, list(range(6)))
                self.assertEqual(context.collect_calls, 1)
                self.assertTrue(any(not b.destroyed for b in context.broadcasts))
                for task in range(1, 6):
                    self.assertEqual(next(results), (task*7, True))
                self.assertEqual(context.collect_calls, 1)
                self.assertEqual(next(results), (42, True))
                self.assertEqual(context.collect_calls, 2)
                self.assertEqual(consumed, list(range(12)))
                results.close()
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))
            self.assertEqual(context.properties['spark.job.description'], 'original description')

        def test_incomplete_wave_fails_before_yielding_results(self):
            from types import SimpleNamespace
            context = FakeContext()
            context.drop_result = True
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context), progress=False)
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                results = pool.iter_map(namespace['_pool_task'], [1, 2], {'factor': [3]})
                with self.assertRaisesRegex(RuntimeError, 'missing, duplicate or out-of-order'):
                    next(results)
            self.assertEqual(pool.last_call['tasks'], 0)
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))
    return unittest.defaultTestLoader.loadTestsFromTestCase(PoolTests)


def main():
    os.chdir(HERE)
    namespace = load_definitions()
    with tempfile.TemporaryDirectory(prefix="spark_v2_validation_") as work:
        namespace["SELFTEST_TMP"] = work
        cfg = namespace["make_config"]("selftest", root=work, out_root=work,
                                       random_pairs=150_000, dedup_random_pairs=150_000,
                                       sim_records=4_000, chunk_size=700, bootstrap_reps=40,
                                       self_check=False)
        namespace["_T"]["cfg"] = cfg
        namespace["_T"]["maps"] = namespace["load_mappings"](HERE / "mappings")
        namespace["_T"]["ref"] = namespace["load_reference"](HERE / "reference", cfg.core)
        namespace["CFG"] = cfg
        namespace["PAR"] = namespace["Parallel"](1, pairs_per_task=100_000)
        pool_result = unittest.TextTestRunner(verbosity=2, failfast=True).run(pool_suite(namespace))
        if not pool_result.wasSuccessful():
            return 1
        if "--full" in sys.argv:
            result, text = namespace["run_selftests"](verbosity=2)
            print(text)
        else:
            suite = unittest.TestSuite()
            for name in ("TestSparkV2Memory", "TestParallel", "TestEMBootstrap"):
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[name]))
            result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
        print(f"Parsed every code cell; ran {result.testsRun} tests, {len(result.skipped)} skipped")
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
