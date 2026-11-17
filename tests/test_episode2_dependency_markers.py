"""The real pinned Torch wheel's Linux NCCL predicate must retain exact scope."""
import pytest

from runpod_benchmark.dependency_validator import Distribution, Lock, validate

ENV = {"python_version": "3.12", "python_full_version": "3.12.3", "sys_platform": "linux",
       "platform_machine": "x86_64", "platform_system": "Linux", "os_name": "posix",
       "implementation_name": "cpython", "implementation_version": "3.12.3",
       "platform_python_implementation": "CPython", "platform_release": "x", "platform_version": "x"}


def check(marker, *, required="2.29.7", nccl="2.30.7", torch="2.13.0+cu130", environment=None):
    packages = {"sglang": "0.5.20", "sglang-kernel": "0.4.7", "torch": torch,
                "triton": "3.7.1", "nvidia-nccl-cu13": nccl}
    requirement = f"nvidia-nccl-cu13=={required}" + (f"; {marker}" if marker else "")
    distributions = [Distribution("sglang", "0.5.20", ("torch==2.13.0",), ("all",)),
                     Distribution("sglang-kernel", "0.4.7"),
                     Distribution("torch", torch, (requirement, "triton==3.7.1")),
                     Distribution("triton", "3.7.1"), Distribution("nvidia-nccl-cu13", nccl)]
    return validate(runtime="sglang", lock=Lock("a" * 64, packages, {k: 1 for k in packages}),
                    distributions=distributions, marker_environment=environment or ENV)


@pytest.mark.parametrize("marker", ['platform_system == "Linux"', '(platform_system == \'Linux\')',
                                   'sys_platform == "linux"'])
def test_exact_linux_atomic_predicates_preserve_canonical_exception(marker):
    result = check(marker)
    assert result["status"] == "pass", result["errors"]
    assert result["allowed_dependency_mismatches"] == [{"package": "torch", "dependency": "nvidia-nccl-cu13",
        "required": "==2.29.7", "marker": 'sys_platform == "linux"', "installed": "2.30.7"}]


@pytest.mark.parametrize("marker", [None, 'os_name == "posix"', 'platform_system != "Windows"',
    'platform_system in "Linux"', 'platform_system == "linux"', 'platform_system == "Darwin"',
    'platform_system == "Linux" or platform_system == "Darwin"',
    'platform_system == "Linux" and python_version >= "3.12"',
    'platform_system == "Linux" and extra == "debug"'])
def test_broader_narrower_or_nonlinux_predicates_are_not_exception_authority(marker):
    assert check(marker)["status"] == "fail"


@pytest.mark.parametrize("change", [{"required": "2.29.6"}, {"nccl": "2.30.8"},
                                     {"torch": "2.13.1+cu130"}])
def test_linux_equivalence_does_not_change_package_or_version_identity(change):
    assert check('platform_system == "Linux"', **change)["status"] == "fail"


def test_incoherent_linux_environment_cannot_authorize_exception():
    assert check('sys_platform == "linux"', environment={**ENV, "platform_system": "Windows"})["status"] == "fail"
