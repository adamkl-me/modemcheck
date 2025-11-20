"""
Docker container control utilities for infrastructure failure testing.

This module provides utilities to pause/unpause Docker containers to simulate
infrastructure failures (database connection loss, Redis unavailability, etc.)
during testing.

WARNING: These utilities directly manipulate Docker containers and should ONLY
be used in test environments.
"""
import subprocess
import time
from typing import Optional


class DockerContainerController:
    """Controller for pausing and unpausing Docker containers during tests."""

    def __init__(self, container_name: str):
        """
        Initialize controller for a specific container.

        Args:
            container_name: Name of the Docker container to control
        """
        self.container_name = container_name
        self._is_paused = False

    def pause(self) -> bool:
        """
        Pause the container to simulate service unavailability.

        Returns:
            True if successfully paused, False otherwise
        """
        try:
            result = subprocess.run(
                ["docker", "pause", self.container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self._is_paused = True
                return True
            else:
                print(f"Failed to pause {self.container_name}: {result.stderr}")
                return False
        except Exception as e:
            print(f"Exception pausing {self.container_name}: {e}")
            return False

    def unpause(self) -> bool:
        """
        Unpause the container to restore service.

        Returns:
            True if successfully unpaused, False otherwise
        """
        try:
            result = subprocess.run(
                ["docker", "unpause", self.container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self._is_paused = False
                return True
            else:
                print(f"Failed to unpause {self.container_name}: {result.stderr}")
                return False
        except Exception as e:
            print(f"Exception unpausing {self.container_name}: {e}")
            return False

    def is_running(self) -> bool:
        """
        Check if the container is running (not paused, not stopped).

        Returns:
            True if container is running and not paused
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format={{.State.Status}}", self.container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                status = result.stdout.strip()
                return status == "running"
            return False
        except Exception:
            return False

    def ensure_unpaused(self):
        """
        Ensure container is unpaused (for cleanup in test teardown).

        This method is safe to call even if the container isn't paused.
        """
        if self._is_paused or not self.is_running():
            self.unpause()
            # Give container time to fully resume
            time.sleep(2)

    def __enter__(self):
        """Context manager entry - pause the container."""
        self.pause()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure container is unpaused."""
        self.ensure_unpaused()
        return False


# Container name constants for test environment
REDIS_CONTAINER = "modemcheck-redis-test"
POSTGRES_CONTAINER = "modemcheck-postgres-test"
API_CONTAINER = "modemcheck-cloud-test"


def pause_redis() -> DockerContainerController:
    """
    Get a controller for pausing the Redis container.

    Returns:
        DockerContainerController instance for Redis

    Example:
        with pause_redis() as controller:
            # Redis is now paused
            response = await client.get("/api/endpoint")
            # Should handle Redis unavailability gracefully
        # Redis is automatically unpaused after 'with' block
    """
    return DockerContainerController(REDIS_CONTAINER)


def pause_postgres() -> DockerContainerController:
    """
    Get a controller for pausing the PostgreSQL container.

    Returns:
        DockerContainerController instance for PostgreSQL

    Example:
        with pause_postgres() as controller:
            # PostgreSQL is now paused
            response = await client.get("/api/endpoint")
            # Should handle database unavailability gracefully
        # PostgreSQL is automatically unpaused after 'with' block
    """
    return DockerContainerController(POSTGRES_CONTAINER)
