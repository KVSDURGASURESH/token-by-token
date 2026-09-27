"""Closed validation and durable capture of non-promotable provider failures."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .episode1_capture import IntegrityError, canonical, sha

HEX64=re.compile(r"[0-9a-f]{64}")
SAFE_POD_ID=re.compile(r"[A-Za-z0-9_-]+",re.ASCII)
MAX_PROVIDER_ARTIFACT_BYTES=16*1024*1024
MAX_INVENTORY_PAGES=4096
CALL_KEYS={"schema_version","delete_attempt","kind","call_index","run_id","attempt_id",
    "plan_sha256","resource_identity_sha256","ownership_identity_sha256",
    "absolute_deadline_monotonic_ns","failure_stage","provider_call","artifact_sha256"}
TERMINAL_KEYS={"schema_version","delete_attempt","kind","run_id","attempt_id",
    "plan_sha256","resource_identity_sha256","ownership_identity_sha256",
    "absolute_deadline_monotonic_ns","status","complete","resource_absent","failure_stage",
    "provider_call_artifact_sha256","validated_inventory_pages","artifact_sha256"}
BASE_CALL_KEYS={"schema_version","role","delete_attempt","run_id","attempt_id","plan_sha256",
    "resource_identity_sha256","ownership_identity_sha256","http_method","request_path",
    "request_query","http_status","request_started_monotonic_ns","body_complete_monotonic_ns",
    "absolute_deadline_monotonic_ns","operation_deadline_monotonic_ns","raw_body_sha256",
    "raw_body_base64","artifact_sha256"}
KINDS={"delete_ack":("delete-response","DELETE"),"inventory_read":("inventory-page","GET"),
       "direct_read":("direct-after-delete","GET")}
STAGES={"call_artifact","http_status","schema","pagination","retention","manifest","capture","deadline"}
AUTHORITY_KEYS={"schema_version","plan_sha256","private_id","unique_name","client_correlation_token",
    "billing_started_monotonic_ns","original_t0_monotonic_ns","hard_deadline_monotonic_ns",
    "teardown_deadline_monotonic_ns","clock_domain","boot_id"}


def _strict_json(raw: bytes) -> dict[str,Any]:
    def pairs(items: list[tuple[str,Any]]) -> dict[str,Any]:
        out={}
        for key,value in items:
            if key in out: raise IntegrityError("duplicate JSON key")
            out[key]=value
        return out
    def number(value: str) -> float:
        result=float(value)
        if not math.isfinite(result): raise IntegrityError("nonfinite JSON")
        return result
    try:
        value=json.loads(raw.decode("utf-8","strict"),object_pairs_hook=pairs,
            parse_constant=lambda _v: (_ for _ in ()).throw(IntegrityError("nonfinite JSON")),
            parse_float=number)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError,OverflowError) as exc:
        raise IntegrityError("invalid provider failure JSON") from exc
    if not isinstance(value,dict): raise IntegrityError("provider failure JSON is not an object")
    return value


def _bounded_authority(directory: Any) -> dict[str,Any]:
    path=os.path.join(os.fspath(directory),"cleanup-authority.json")
    flags=(os.O_RDONLY | getattr(os,"O_NOFOLLOW",0) |
           getattr(os,"O_NONBLOCK",0) | getattr(os,"O_CLOEXEC",0))
    try: fd=os.open(path,flags)
    except OSError as exc: raise IntegrityError("cleanup authority is unavailable") from exc
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or
                before.st_size>65536 or before.st_mode & 0o077):
            raise IntegrityError("cleanup authority is not a bounded private regular file")
        chunks=[]; remaining=before.st_size
        while remaining:
            chunk=os.read(fd,min(remaining,65536))
            if not chunk: raise IntegrityError("cleanup authority was truncated")
            chunks.append(chunk); remaining-=len(chunk)
        if os.read(fd,1): raise IntegrityError("cleanup authority changed while reading")
        after=os.fstat(fd)
        identity=lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_nlink,
            value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if identity(after)!=identity(before):
            raise IntegrityError("cleanup authority changed while reading")
    finally: os.close(fd)
    return _strict_json(b"".join(chunks))


@dataclass(frozen=True)
class CaptureFailureSink:
    """Validate each envelope against durable authority before synchronous capture."""
    capture: Any

    def __post_init__(self) -> None:
        authority=_bounded_authority(self.capture.directory)
        if set(authority)!=AUTHORITY_KEYS or authority.get("schema_version")!="episode1.cleanup-authority.v2":
            raise IntegrityError("cleanup authority fields are not closed")
        contract=self.capture.contract
        if (authority.get("plan_sha256")!=contract.plan_sha256 or
                authority.get("hard_deadline_monotonic_ns")!=contract.hard_deadline_monotonic_ns):
            raise IntegrityError("cleanup authority contract binding mismatch")
        private_id=authority.get("private_id"); name=authority.get("unique_name")
        token=authority.get("client_correlation_token"); billing_ns=authority.get("billing_started_monotonic_ns")
        if (not isinstance(private_id,str) or not private_id or not isinstance(name,str) or not name or
                not isinstance(token,str) or not token or isinstance(billing_ns,bool) or not isinstance(billing_ns,int)):
            raise IntegrityError("cleanup authority identity is invalid")
        resource=self.capture._cleanup_resource_identity_sha256
        if not isinstance(resource,str) or HEX64.fullmatch(resource) is None:
            raise IntegrityError("capture lacks a durable cleanup resource identity")
        ownership=sha(canonical({"provider":"runpod-rest-v2","private_id":private_id,
            "unique_name":name,"ownership_token_sha256":sha(token.encode()),
            "billing_started_monotonic_ns":billing_ns}))
        object.__setattr__(self,"private_id",private_id)
        object.__setattr__(self,"ownership_identity_sha256",ownership)
        object.__setattr__(self,"_calls",{})
        object.__setattr__(self,"_last_completion",{})
        object.__setattr__(self,"_validated_pages",{})
        object.__setattr__(self,"_validated_page_bytes",{})

    def __call__(self, observation: Any) -> None:
        raw=getattr(observation,"evidence_bytes",None); claimed=getattr(observation,"evidence_sha256",None)
        if not isinstance(raw,bytes) or len(raw)>16*1024*1024:
            raise IntegrityError("provider failure observation is unbounded")
        if not isinstance(claimed,str) or HEX64.fullmatch(claimed) is None or sha(raw)!=claimed:
            raise IntegrityError("provider failure observation digest mismatch")
        value=_strict_json(raw); schema=value.get("schema_version")
        if schema=="episode1.provider-cleanup-failure-call.v1": pending=self._call(value)
        elif schema=="episode1.provider-cleanup-failure-terminal.v1": pending=self._terminal(value)
        else: raise IntegrityError("provider failure observation schema is unsupported")
        self.capture.provider_failure_observed(observation)
        action,key,digest,complete,page=pending
        if action=="append":
            self._calls.setdefault(key,[]).append(digest)
            self._last_completion[key]=complete
            if page is not None:
                projection,size=page
                self._validated_pages.setdefault(key,[]).append(projection)
                self._validated_page_bytes[key]=self._validated_page_bytes.get(key,0)+size
        else:
            self._calls.pop(key,None); self._last_completion.pop(key,None)
            self._validated_pages.pop(key,None)
            self._validated_page_bytes.pop(key,None)

    def _common(self,value: Mapping[str,Any]) -> tuple[int,str]:
        attempt=value.get("delete_attempt"); kind=value.get("kind"); contract=self.capture.contract
        if isinstance(attempt,bool) or not isinstance(attempt,int) or attempt<1: raise IntegrityError("delete attempt is invalid")
        if kind not in KINDS or value.get("failure_stage") not in STAGES: raise IntegrityError("provider failure kind/stage is invalid")
        if (value.get("run_id")!=contract.run_id or value.get("attempt_id")!=contract.attempt_id or
                value.get("plan_sha256")!=contract.plan_sha256 or
                value.get("resource_identity_sha256")!=self.capture._cleanup_resource_identity_sha256 or
                value.get("ownership_identity_sha256")!=self.ownership_identity_sha256 or
                value.get("absolute_deadline_monotonic_ns")!=contract.hard_deadline_monotonic_ns):
            raise IntegrityError("provider failure binding mismatch")
        bare={k:v for k,v in value.items() if k!="artifact_sha256"}
        if value.get("artifact_sha256")!=sha(canonical(bare)): raise IntegrityError("provider failure artifact hash mismatch")
        return attempt,kind

    def _call(self,value: Mapping[str,Any]) -> tuple[
        str,tuple[int,str],str,int,tuple[dict[str,Any],int]|None,
    ]:
        if set(value)!=CALL_KEYS: raise IntegrityError("provider failure call fields are not closed")
        attempt,kind=self._common(value); index=value.get("call_index")
        if isinstance(index,bool) or not isinstance(index,int) or index<1: raise IntegrityError("provider failure call index is invalid")
        call=value.get("provider_call")
        if not isinstance(call,dict): raise IntegrityError("provider failure provider-call is invalid")
        complete,body=self._provider_call(call,kind,attempt)
        key=(attempt,kind); calls=self._calls.get(key,[])
        if index!=len(calls)+1: raise IntegrityError("provider failure calls are not contiguous")
        page=self._validated_inventory_page(call,body,key) if kind=="inventory_read" else None
        return "append",key,call["artifact_sha256"],complete,page

    def _provider_call(self,call: Mapping[str,Any],kind: str,attempt: int) -> tuple[int,bytes]:
        failed=call.get("schema_version")=="episode1.provider-failed-http-call.v1"
        expected=BASE_CALL_KEYS | ({"validation_error"} if failed else set())
        if set(call)!=expected: raise IntegrityError("provider failure provider-call fields are not closed")
        role,method=KINDS[kind]; contract=self.capture.contract
        if (call.get("role")!=role or call.get("http_method")!=method or call.get("delete_attempt")!=attempt or
                call.get("run_id")!=contract.run_id or call.get("attempt_id")!=contract.attempt_id or
                call.get("plan_sha256")!=contract.plan_sha256 or
                call.get("resource_identity_sha256")!=self.capture._cleanup_resource_identity_sha256 or
                call.get("ownership_identity_sha256")!=self.ownership_identity_sha256 or
                call.get("absolute_deadline_monotonic_ns")!=contract.hard_deadline_monotonic_ns):
            raise IntegrityError("provider call binding mismatch")
        if not failed and call.get("schema_version")!="episode1.provider-call-evidence.v1":
            raise IntegrityError("provider call schema is invalid")
        path=call.get("request_path"); query=call.get("request_query")
        if kind=="inventory_read":
            if path!="/pods" or not isinstance(query,dict): raise IntegrityError("inventory call target is invalid")
            if set(query) not in ({"includeClusterPods","limit"},
                                  {"includeClusterPods","limit","cursor"}):
                raise IntegrityError("inventory call query is invalid")
            if query.get("includeClusterPods")!="true" or query.get("limit")!="1000":
                raise IntegrityError("inventory call query is invalid")
            if "cursor" in query and (not isinstance(query["cursor"],str) or not query["cursor"]):
                raise IntegrityError("inventory call cursor is invalid")
        elif path!="/pods/"+self.private_id or query!={}: raise IntegrityError("provider call owned target is invalid")
        values=(call.get("http_status"),call.get("request_started_monotonic_ns"),
            call.get("body_complete_monotonic_ns"),call.get("operation_deadline_monotonic_ns"))
        if any(isinstance(x,bool) or not isinstance(x,int) for x in values): raise IntegrityError("provider call typed fields are invalid")
        status,start,complete,operation_deadline=values
        if (not 100<=status<=599 or start<0 or not start<=complete or
                not 0<operation_deadline<=contract.hard_deadline_monotonic_ns):
            raise IntegrityError("provider call timing/status is invalid")
        if not failed and complete>=operation_deadline: raise IntegrityError("successful provider call exceeded its deadline")
        if failed and call.get("validation_error") not in {"invalid_body","late_response","http_status"}:
            raise IntegrityError("failed provider call validation error is invalid")
        key=(attempt,kind); prior=self._last_completion.get(key)
        if prior is not None and start<prior: raise IntegrityError("provider calls overlap or are out of order")
        try: body=base64.b64decode(call.get("raw_body_base64"),validate=True)
        except (TypeError,ValueError) as exc: raise IntegrityError("provider call body encoding is invalid") from exc
        if len(body)>2*1024*1024 or sha(body)!=call.get("raw_body_sha256"): raise IntegrityError("provider call body is invalid")
        bare={k:v for k,v in call.items() if k!="artifact_sha256"}
        if call.get("artifact_sha256")!=sha(canonical(bare)): raise IntegrityError("provider call artifact hash mismatch")
        return complete,body

    def _validated_inventory_page(
        self, call: Mapping[str,Any], body: bytes, key: tuple[int,str],
    ) -> tuple[dict[str,Any],int]|None:
        """Derive one validated page only from its exact retained call bytes."""
        if (call.get("schema_version")!="episode1.provider-call-evidence.v1" or
                call.get("http_status")!=200):
            return None
        try: parsed=_strict_json(body)
        except IntegrityError: return None
        if set(parsed)!={"pods","pagination"} or not isinstance(parsed.get("pods"),list):
            return None
        pagination=parsed.get("pagination")
        if (not isinstance(pagination,dict) or set(pagination)!={"nextCursor","hasNextPage"} or
                not isinstance(pagination.get("hasNextPage"),bool)):
            return None
        for pod in parsed["pods"]:
            if (not isinstance(pod,dict) or not isinstance(pod.get("id"),str) or
                    SAFE_POD_ID.fullmatch(pod["id"]) is None):
                return None
        prior=self._validated_pages.get(key,[])
        calls=self._calls.get(key,[])
        # A validated prefix cannot skip an earlier retained call. Once a
        # call fails page validation, later calls remain raw evidence but
        # cannot re-enter the prefix.
        if len(prior)!=len(calls): return None
        # A terminal page closes the cursor chain. A later no-cursor call is
        # evidence of an invalid extra request, not a new first page.
        if prior and not prior[-1]["has_next_page"]: return None
        if len(prior)>=MAX_INVENTORY_PAGES: return None
        query=call["request_query"]
        request_cursor=query.get("cursor")
        expected_cursor=None if not prior else prior[-1]["next_cursor"]
        if request_cursor!=expected_cursor or (not prior and "cursor" in query):
            return None
        has_next=pagination["hasNextPage"]; next_cursor=pagination["nextCursor"]
        if has_next:
            seen={page["next_cursor"] for page in prior}
            if not isinstance(next_cursor,str) or not next_cursor or next_cursor in seen:
                return None
        elif next_cursor is not None:
            return None
        page=dict(call)
        page.update(sequence=len(prior)+1,request_cursor=request_cursor,
                    has_next_page=has_next,next_cursor=next_cursor)
        bare=dict(page); bare.pop("artifact_sha256")
        page_digest=sha(canonical(bare))
        page["artifact_sha256"]=page_digest
        page_bytes=len(canonical(page))
        if self._validated_page_bytes.get(key,0)+page_bytes>MAX_PROVIDER_ARTIFACT_BYTES:
            return None
        return ({"sequence":page["sequence"],"request_cursor":request_cursor,
                "has_next_page":has_next,"next_cursor":next_cursor,
                "page_artifact_sha256":page_digest},page_bytes)

    def _terminal(self,value: Mapping[str,Any]) -> tuple[
        str,tuple[int,str],str,int,tuple[dict[str,Any],int]|None,
    ]:
        if set(value)!=TERMINAL_KEYS: raise IntegrityError("provider failure terminal fields are not closed")
        attempt,kind=self._common(value)
        if value.get("status")!="failed" or value.get("complete") is not False or value.get("resource_absent") is not None:
            raise IntegrityError("provider failure terminal result is invalid")
        expected=self._calls.get((attempt,kind),[]); digests=value.get("provider_call_artifact_sha256")
        if not isinstance(digests,list) or digests!=expected or not digests: raise IntegrityError("provider failure terminal call chain mismatch")
        pages=value.get("validated_inventory_pages")
        expected_pages=self._validated_pages.get((attempt,kind),[])
        if not isinstance(pages,list) or pages!=expected_pages:
            raise IntegrityError("provider failure inventory prefix does not match retained calls")
        if kind!="inventory_read" and pages:
            raise IntegrityError("non-inventory failure has page prefix")
        return "finish",(attempt,kind),"",0,None
