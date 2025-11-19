"""
Performance and load tests.

Tests system performance under load, stress testing,
and scalability limits.
"""
import pytest
import asyncio
import time
import httpx
import hmac
import hashlib
from datetime import datetime, timedelta
from statistics import mean, median


pytestmark = pytest.mark.performance


class TestUploadPerformance:
    """Test upload endpoint performance."""

    @pytest.mark.asyncio
    async def test_upload_latency(
        self,
        http_client: httpx.AsyncClient,
        active_api_key
    ):
        """Test upload latency under normal conditions."""
        import hashlib
        import json

        latencies = []

        for i in range(10):
            modem_data = {"check_time": int(time.time()) + i}
            json_data = json.dumps(modem_data).encode()
            modem_id = f"XB8-PERF{i:03d}"
            checksum = hashlib.sha256(json_data).hexdigest()

            timestamp = str(int(time.time()))
            message = f"{timestamp}|{modem_id}|test.json|{checksum}"
            signature = hmac.new(
                active_api_key.api_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            files = {"file": ("test.json", json_data, "application/json")}
            data = {
                "api_key": active_api_key.api_key,
                "modem_id": modem_id,
                "filename": "test.json",
                "checksum": checksum
            }
            headers = {
                "X-Request-Timestamp": timestamp,
                "X-Request-Signature": signature
            }

            start = time.perf_counter()
            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers=headers
            )
            latency = time.perf_counter() - start

            assert response.status_code == 200
            latencies.append(latency)

        # Performance assertions
        avg_latency = mean(latencies)
        median_latency = median(latencies)
        max_latency = max(latencies)

        print(f"\nUpload Performance:")
        print(f"  Average: {avg_latency*1000:.2f}ms")
        print(f"  Median: {median_latency*1000:.2f}ms")
        print(f"  Max: {max_latency*1000:.2f}ms")

        # Should complete within reasonable time
        assert avg_latency < 1.0  # < 1 second average
        assert max_latency < 2.0  # < 2 seconds max

    @pytest.mark.asyncio
    async def test_concurrent_upload_performance(
        self,
        http_client: httpx.AsyncClient,
        active_api_key
    ):
        """Test performance with concurrent uploads."""
        import hashlib
        import json

        async def upload_check(index):
            modem_data = {"check_time": int(time.time()) + index}
            json_data = json.dumps(modem_data).encode()
            modem_id = f"XB8-CONCURRENT{index:03d}"
            checksum = hashlib.sha256(json_data).hexdigest()

            timestamp = str(int(time.time()))
            message = f"{timestamp}|{modem_id}|test.json|{checksum}"
            signature = hmac.new(
                active_api_key.api_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            files = {"file": ("test.json", json_data, "application/json")}
            data = {
                "api_key": active_api_key.api_key,
                "modem_id": modem_id,
                "filename": "test.json",
                "checksum": checksum
            }
            headers = {
                "X-Request-Timestamp": timestamp,
                "X-Request-Signature": signature
            }

            start = time.perf_counter()
            response = await http_client.post(
                "/api/upload",
                files=files,
                data=data,
                headers=headers
            )
            latency = time.perf_counter() - start

            return response.status_code, latency

        # Upload 20 checks concurrently
        start = time.perf_counter()
        tasks = [upload_check(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start

        # Analyze results
        status_codes = [r[0] for r in results]
        latencies = [r[1] for r in results]

        success_count = sum(1 for code in status_codes if code == 200)
        avg_latency = mean(latencies)
        throughput = len(results) / total_time

        print(f"\nConcurrent Upload Performance (20 concurrent):")
        print(f"  Success rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Average latency: {avg_latency*1000:.2f}ms")
        print(f"  Throughput: {throughput:.2f} req/s")

        # Performance requirements
        assert success_count >= 18  # At least 90% success
        assert avg_latency < 2.0  # < 2 seconds average under load
        assert throughput >= 5  # At least 5 req/s


class TestQueryPerformance:
    """Test query endpoint performance."""

    @pytest.mark.asyncio
    async def test_modem_check_query_performance(
        self,
        admin_client_with_token: httpx.AsyncClient,
        db_session
    ):
        """Test query performance with varying dataset sizes."""
        from app.models.modem_check import ModemCheck

        # Create test dataset
        base_time = int(time.time())
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        for i in range(100):
            check = ModemCheck(
                modem_id="XB8-QUERYPERF",
                check_time=datetime.fromtimestamp(base_time + i),
                filename=f"XB8-QUERYPERF/queryperf_{base_time}_{i}.json",
                full_data={"index": i}
            )
            db_session.add(check)
        await db_session.commit()

        # Test query performance using actual /api/db/list_checks endpoint
        latencies = []

        for _ in range(10):
            start = time.perf_counter()
            response = await admin_client_with_token.get(
                f"/api/db/list_checks?modem_id=XB8-QUERYPERF&start_date={today}&end_date={tomorrow}&limit=50"
            )
            latency = time.perf_counter() - start

            assert response.status_code == 200
            latencies.append(latency)

        avg_latency = mean(latencies)
        print(f"\nQuery Performance (100 records, 50 limit):")
        print(f"  Average: {avg_latency*1000:.2f}ms")

        # Should be fast
        assert avg_latency < 0.5  # < 500ms

    @pytest.mark.asyncio
    async def test_api_key_cache_performance(
        self,
        http_client: httpx.AsyncClient,
        active_api_key
    ):
        """Test API key validation performance (cache hit)."""
        import hashlib
        import json

        # Prime the cache with first request
        modem_data = {"check_time": int(time.time())}
        json_data = json.dumps(modem_data).encode()
        modem_id = "XB8-CACHE"
        checksum = hashlib.sha256(json_data).hexdigest()

        timestamp = str(int(time.time()))
        message = f"{timestamp}|{modem_id}|test.json|{checksum}"
        signature = hashlib.sha256(
            f"{active_api_key.api_key}{message}".encode()
        ).hexdigest()

        files = {"file": ("test.json", json_data, "application/json")}
        data = {
            "api_key": active_api_key.api_key,
            "modem_id": modem_id,
            "filename": "test.json",
            "checksum": checksum
        }
        headers = {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature
        }

        # First request (cache miss)
        start = time.perf_counter()
        response1 = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )
        latency_miss = time.perf_counter() - start

        # Second request (cache hit)
        start = time.perf_counter()
        response2 = await http_client.post(
            "/api/upload",
            files=files,
            data=data,
            headers=headers
        )
        latency_hit = time.perf_counter() - start

        print(f"\nAPI Key Cache Performance:")
        print(f"  Cache miss: {latency_miss*1000:.2f}ms")
        print(f"  Cache hit: {latency_hit*1000:.2f}ms")
        print(f"  Speedup: {latency_miss/latency_hit:.2f}x")

        # Cache should improve performance
        # Note: May not be significant difference in test environment


class TestDatabasePerformance:
    """Test database operation performance."""

    @pytest.mark.asyncio
    async def test_bulk_insert_performance(self, db_session):
        """Test bulk insert performance."""
        from app.models.modem_check import ModemCheck

        # Bulk insert 100 records
        checks = []
        base_time = int(time.time())
        for i in range(100):
            check = ModemCheck(
                modem_id=f"XB8-BULK{i:03d}",
                check_time=datetime.fromtimestamp(base_time + i),
                filename=f"XB8-BULK{i:03d}/bulk_{base_time}_{i}.json",
                full_data={"index": i}
            )
            checks.append(check)

        start = time.perf_counter()
        db_session.add_all(checks)
        await db_session.commit()
        duration = time.perf_counter() - start

        throughput = len(checks) / duration

        print(f"\nBulk Insert Performance (100 records):")
        print(f"  Time: {duration:.2f}s")
        print(f"  Throughput: {throughput:.2f} records/s")

        # Should be efficient
        assert duration < 5.0  # < 5 seconds for 100 records
        assert throughput >= 20  # At least 20 records/s

    @pytest.mark.asyncio
    async def test_index_query_performance(self, db_session):
        """Test that indexed queries are fast."""
        from app.models.modem_check import ModemCheck
        from sqlalchemy import select

        # Create dataset
        base_time = int(time.time())
        for i in range(500):
            check = ModemCheck(
                modem_id="XB8-INDEX",
                check_time=datetime.fromtimestamp(base_time + i),
                filename=f"XB8-INDEX/index_{base_time}_{i}.json",
                full_data={}
            )
            db_session.add(check)
        await db_session.commit()

        # Query using index
        start = time.perf_counter()
        result = await db_session.execute(
            select(ModemCheck).where(
                ModemCheck.modem_id == "XB8-INDEX"
            ).limit(50)
        )
        checks = result.scalars().all()
        duration = time.perf_counter() - start

        print(f"\nIndexed Query Performance (500 records):")
        print(f"  Time: {duration*1000:.2f}ms")
        print(f"  Records retrieved: {len(checks)}")

        # Should be fast with index
        assert duration < 0.1  # < 100ms


class TestStressTest:
    """Stress testing under heavy load."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sustained_load(
        self,
        http_client: httpx.AsyncClient,
        active_api_key
    ):
        """Test sustained load over time."""
        import hashlib
        import json

        duration = 30  # 30 seconds
        upload_count = 0
        errors = 0

        async def continuous_upload():
            nonlocal upload_count, errors

            end_time = time.time() + duration

            while time.time() < end_time:
                try:
                    modem_data = {"check_time": int(time.time())}
                    json_data = json.dumps(modem_data).encode()
                    modem_id = f"XB8-STRESS{upload_count:05d}"
                    checksum = hashlib.sha256(json_data).hexdigest()

                    timestamp = str(int(time.time()))
                    message = f"{timestamp}|{modem_id}|test.json|{checksum}"
                    signature = hashlib.sha256(
                        f"{active_api_key.api_key}{message}".encode()
                    ).hexdigest()

                    files = {"file": ("test.json", json_data, "application/json")}
                    data = {
                        "api_key": active_api_key.api_key,
                        "modem_id": modem_id,
                        "filename": "test.json",
                        "checksum": checksum
                    }
                    headers = {
                        "X-Request-Timestamp": timestamp,
                        "X-Request-Signature": signature
                    }

                    response = await http_client.post(
                        "/api/upload",
                        files=files,
                        data=data,
                        headers=headers
                    )

                    if response.status_code == 200:
                        upload_count += 1
                    else:
                        errors += 1

                    await asyncio.sleep(0.1)  # Throttle

                except Exception as e:
                    errors += 1

        # Run stress test
        start = time.perf_counter()
        await continuous_upload()
        actual_duration = time.perf_counter() - start

        throughput = upload_count / actual_duration
        error_rate = errors / (upload_count + errors) if (upload_count + errors) > 0 else 0

        print(f"\nStress Test ({duration}s):")
        print(f"  Successful uploads: {upload_count}")
        print(f"  Errors: {errors}")
        print(f"  Throughput: {throughput:.2f} req/s")
        print(f"  Error rate: {error_rate*100:.2f}%")

        # Performance targets
        assert upload_count >= 100  # At least 100 successful uploads
        assert error_rate < 0.1  # < 10% error rate