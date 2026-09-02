from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

class KnowledgeLibraryVerificationError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class Lesson:
    chapter_id: str
    lesson_id: str
    title: str
    position: int
    content_path: str
    content_sha256: str
    source_artifact_version: str

class StaticKnowledgeLibrary:
    def __init__(self, content_root: str | Path | None = None) -> None:
        self.content_root = Path(content_root) if content_root is not None else Path(__file__).resolve().parent / "content"
        self._lessons = ()

    @staticmethod
    def _canonical(v):
        return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")

    @staticmethod
    def _sha(raw):
        return hashlib.sha256(raw).hexdigest()

    def verify(self):
        manifest=json.loads((self.content_root/"CONTENT_MANIFEST.json").read_text(encoding="utf-8"))
        curriculum=json.loads((self.content_root/"CURRICULUM.json").read_text(encoding="utf-8"))
        claimed=str(manifest.get("manifest_sha256","")); m0=dict(manifest); m0.pop("manifest_sha256",None)
        if self._sha(self._canonical(m0))!=claimed: raise KnowledgeLibraryVerificationError("CONTENT_MANIFEST_SHA_MISMATCH")
        rows=list(manifest.get("lessons",[]))
        if not rows: raise KnowledgeLibraryVerificationError("EMPTY_ACTIVE_CURRICULUM")
        seen=set(); loaded=[]; idx=[]
        for item in rows:
            if item.get("content_class")!="GENERAL_MARKET_KNOWLEDGE": raise KnowledgeLibraryVerificationError("NON_LAYER_A_CONTENT")
            if item.get("source_code_conformance")!="NOT_APPLICABLE": raise KnowledgeLibraryVerificationError("INVALID_SOURCE_CODE_CONFORMANCE")
            if (item.get("factual_review") or {}).get("status")!="REVIEWED": raise KnowledgeLibraryVerificationError("UNREVIEWED_ACTIVE_LESSON")
            p=int(item["position"])
            if p in seen: raise KnowledgeLibraryVerificationError("DUPLICATE_CURRICULUM_POSITION")
            seen.add(p); rel=str(item["content_path"]); raw=(self.content_root/rel).read_bytes(); actual=self._sha(raw)
            if actual!=item["content_sha256"]: raise KnowledgeLibraryVerificationError("CONTENT_SHA_MISMATCH:"+str(item["lesson_id"]))
            loaded.append(Lesson(str(item["chapter_id"]),str(item["lesson_id"]),str(item["title"]),p,rel,actual,str(item["source_artifact_version"])))
            idx.append({"curriculum_version":str(curriculum["curriculum_version"]),"chapter_id":str(item["chapter_id"]),"lesson_id":str(item["lesson_id"]),"content_sha256":actual,"position":p})
        loaded.sort(key=lambda x:x.position); idx.sort(key=lambda x:x["position"])
        cs=self._sha(self._canonical(idx))
        if cs!=curriculum.get("curriculum_sha256") or cs!=manifest.get("curriculum_sha256"): raise KnowledgeLibraryVerificationError("CURRICULUM_IDENTITY_MISMATCH")
        self._lessons=tuple(loaded)
        return {"status":"PASS","library_version":manifest["library_version"],"lesson_count":len(loaded),"manifest_sha256":claimed,"curriculum_sha256":cs}

    @property
    def lessons(self):
        if not self._lessons: self.verify()
        return self._lessons

    def read_lesson(self,lesson_id):
        row=next((x for x in self.lessons if x.lesson_id==lesson_id),None)
        if row is None: raise KeyError(lesson_id)
        return (self.content_root/row.content_path).read_text(encoding="utf-8",errors="replace")

    def search(self,query):
        q=query.strip().casefold()
        if not q:return self.lessons
        terms=tuple(x for x in re.split(r"\s+",q) if x); out=[]
        for row in self.lessons:
            text=(row.title+"\n"+self.read_lesson(row.lesson_id)).casefold()
            if all(x in text for x in terms): out.append(row)
        return tuple(out)
