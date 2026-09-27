"""Strict adapters for inspected Leipzig archives; no archive code is executed.

Only observed text enters the matcher input. Gold is a separate equivalence
partition, with upstream pair/partition anomalies preserved in the audit report.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from pathlib import Path,PurePosixPath
import csv
import hashlib
import io
import json
import re
import stat
import unicodedata
import zipfile

import networkx as nx
import pandas as pd


class GoldPartitionError(ValueError):
    def __init__(self,message: str,details: dict):
        super().__init__(message)
        self.details=details


def inspect_zip(archive: str|Path,max_uncompressed: int=20_000_000) -> tuple[dict[str,bytes],list[dict]]:
    """Read bounded members in memory; reject traversal, links and duplicate names."""
    contents={};manifest=[]
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>100 or sum(i.file_size for i in infos)>max_uncompressed:
            raise ValueError("Archive exceeds entry or uncompressed-size cap")
        names=set()
        for item in infos:
            name=item.filename.replace("\\","/");path=PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or ":" in name or
                    stat.S_ISLNK(item.external_attr>>16)):
                raise ValueError(f"Unsafe archive member: {item.filename}")
            if name in names:
                raise ValueError(f"Duplicate archive member: {name}")
            names.add(name)
            if item.is_dir():continue
            payload=z.read(item)
            contents[name]=payload
            manifest.append({"path":name,"bytes":len(payload),
                "sha256":hashlib.sha256(payload).hexdigest()})
    return contents,manifest


def _text(value,field: str) -> str:
    if not isinstance(value,str) or not value.strip():
        raise ValueError(f"Missing or blank observed {field}")
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",value)).strip()


def _id(value,field: str) -> str:
    if isinstance(value,bool) or not isinstance(value,(str,int)) or not str(value).strip():
        raise ValueError(f"Missing or invalid {field}")
    return str(value).strip()


def _opaque(namespace: str,value: str) -> str:
    return hashlib.sha256((namespace+"\0"+value).encode("utf-8")).hexdigest()


def _normalized_frame(dataset: str,records: dict,labels: dict) -> pd.DataFrame:
    if set(records)!=set(labels):
        raise ValueError("Gold labels must cover every record exactly once")
    rows=[{"record_id":"r_"+_opaque(dataset+"_record",raw_id),
           "entity_id":"e_"+_opaque(dataset+"_entity",labels[raw_id]),
           "text":rec["text"],"source":rec["source"]}
          for raw_id,rec in records.items()]
    d=pd.DataFrame(rows,columns=("record_id","entity_id","text","source"))
    if d.record_id.duplicated().any():raise ValueError("Opaque record ID collision")
    # The order is based on observed IDs only, not on gold partition membership.
    return d.sort_values("record_id",kind="stable").reset_index(drop=True)


def affiliation_records(ids_payload: bytes,mapping_payload: bytes) -> tuple[pd.DataFrame,dict]:
    reader=csv.reader(io.StringIO(ids_payload.decode("utf-8-sig")),strict=True)
    if next(reader,None)!=["id1","affil1"]:
        raise ValueError("Affiliation record header must be exactly id1,affil1")
    records={}
    for row in reader:
        if len(row)!=2:raise ValueError("Affiliation record row must have two fields")
        key=_id(row[0],"record ID")
        if key in records:raise ValueError("Duplicate affiliation record ID")
        records[key]={"text":_text(row[1],"affil1"),"source":"leipzig_affiliations"}
    if not records:raise ValueError("No affiliation records")
    directed=[];pairs=set();covered=set()
    for row in csv.reader(io.StringIO(mapping_payload.decode("utf-8-sig")),strict=True):
        if len(row)!=2:raise ValueError("Headerless affiliation mapping requires two IDs per row")
        a,b=(_id(x,"mapping record ID") for x in row)
        if a not in records or b not in records:
            raise ValueError("Affiliation mapping references unknown record ID or has an unexpected header")
        if a==b:raise ValueError("Affiliation mapping contains a self-pair")
        directed.append((a,b));pairs.add(tuple(sorted((a,b))));covered.update((a,b))
    if covered!=set(records):
        raise GoldPartitionError("Affiliation mapping leaves unlabeled records; no singleton inference",
            {"uncovered_record_ids":sorted(set(records)-covered)})
    g=nx.Graph();g.add_nodes_from(records);g.add_edges_from(pairs)
    components=list(nx.connected_components(g));labels={}
    for comp in components:
        entity=min(comp)
        labels.update({key:entity for key in comp})
    closure=sum(len(c)*(len(c)-1)//2 for c in components)
    counts=Counter(directed)
    report={"dataset":"affiliations","gold_status":"equivalence_closure_of_provider_positive_mapping",
        "records":len(records),"entities":len(components),"source_count":1,
        "raw_directed_mapping_rows":len(directed),"unique_directed_mapping_pairs":len(counts),
        "repeated_same_direction_rows":sum(v-1 for v in counts.values()),
        "unique_undirected_mapping_pairs":len(pairs),
        "unordered_true_pairs_after_closure":closure,
        "additional_pairs_implied_by_transitivity":closure-len(pairs),
        "all_pairs_have_reverse":all((b,a) in counts for a,b in directed),
        "uncovered_records":0,"records_removed":0,
        "observed_text_fields":["affil1"],"excluded_fields":["id1","mapping IDs"],
        "corrections":[],"entity_size_counts":dict(sorted(Counter(map(len,components)).items()))}
    return _normalized_frame("affiliations",records,labels),report


def _ndjson(payload: bytes) -> list[dict]:
    result=[]
    for line in payload.decode("utf-8-sig").splitlines():
        if not line.strip():continue
        obj=json.loads(line)
        if not isinstance(obj,dict):raise ValueError("Expected one JSON object per line")
        result.append(obj)
    if not result:raise ValueError("Empty NDJSON file")
    return result


def geographic_records(records_payload: bytes,clusters_payload: bytes,
                       allow_redundant_singleton: bool=False) -> tuple[pd.DataFrame,dict]:
    raw_records=_ndjson(records_payload);raw_clusters=_ndjson(clusters_payload)
    records={}
    for row in raw_records:
        key=_id(row.get("id"),"record ID");data=row.get("data")
        if key in records:raise ValueError("Duplicate geographic record ID")
        if not isinstance(data,dict):raise ValueError("Missing geographic record data")
        records[key]={"text":_text(data.get("label"),"label"),
                      "source":_text(data.get("ontology"),"ontology")}
    clusters={};memberships=defaultdict(list)
    for row in raw_clusters:
        key=_id(row.get("id"),"cluster ID");data=row.get("data")
        if key in clusters:raise ValueError("Duplicate geographic cluster ID")
        if not isinstance(data,dict) or not isinstance(data.get("clusteredVertices"),list):
            raise ValueError("Missing geographic clusteredVertices array")
        members=[_id(x,"cluster member") for x in data["clusteredVertices"]]
        if not members or len(members)!=len(set(members)):
            raise ValueError("Empty cluster or repeated member inside a geographic cluster")
        if not set(members)<=set(records):
            raise ValueError("Geographic cluster references unknown record ID")
        clusters[key]={"members":members,"original_row":row}
        for member in members:memberships[member].append(key)
    uncovered=sorted(set(records)-set(memberships))
    if uncovered:
        raise GoldPartitionError("Geographic gold leaves unlabeled records; no singleton inference",
            {"uncovered_record_ids":uncovered})
    overlaps={key:owners for key,owners in memberships.items() if len(owners)>1}
    corrections=[]
    if overlaps:
        details={"overlapping_memberships":overlaps,"upstream_cluster_rows":len(clusters),
            "original_rows":[v["original_row"] for k,v in clusters.items()
                             if k in {owner for owners in overlaps.values() for owner in owners}]}
        sanctioned=(overlaps=={"4216":["459","4216"]} or overlaps=={"4216":["4216","459"]})
        sanctioned=(sanctioned and set(clusters["459"]["members"])=={"4216","459","460","3790"}
                    and clusters["4216"]["members"]==["4216"])
        if not allow_redundant_singleton or not sanctioned:
            raise GoldPartitionError("Geographic gold is not a partition: overlapping memberships",details)
        corrections.append({"type":"remove_exact_redundant_singleton_cluster_row",
            "record_id":"4216","retained_cluster_id":"459","removed_cluster_id":"4216",
            "removed_original_row":clusters["4216"]["original_row"],
            "reason":"Record already belongs to complete non-singleton cluster 459; no record or pair removed"})
        del clusters["4216"]
    labels={}
    for cluster,data in clusters.items():
        for member in data["members"]:
            if member in labels:raise GoldPartitionError("Unresolved overlapping gold",{"record_id":member})
            labels[member]=cluster
    sizes=[len(c["members"]) for c in clusters.values()]
    report={"dataset":"geographic_corrected_gold" if corrections else "geographic",
        "gold_status":"corrected_upstream_gold" if corrections else "provider_partition",
        "records":len(records),"entities":len(clusters),"upstream_cluster_rows":len(raw_clusters),
        "raw_memberships":sum(len(row["data"]["clusteredVertices"]) for row in raw_clusters),
        "unique_memberships":len(labels),"unordered_true_pairs_after_closure":sum(s*(s-1)//2 for s in sizes),
        "source_count":len({rec["source"] for rec in records.values()}),
        "source_counts":dict(Counter(rec["source"] for rec in records.values())),
        "uncovered_records":0,"records_removed":0,"observed_text_fields":["data.label"],
        "excluded_fields":["id","lat","lon","ontology","clusteredVertices","cluster aggregate label"],
        "corrections":corrections,"entity_size_counts":dict(sorted(Counter(sizes).items()))}
    return _normalized_frame("geographic",records,labels),report


def adapt_archive(dataset: str,archive: str|Path,allow_redundant_singleton: bool=False):
    contents,members=inspect_zip(archive)
    if dataset=="affiliations":
        required=("affiliationstrings_ids.csv","affiliationstrings_mapping.csv")
        if not set(required)<=set(contents):raise ValueError("Missing affiliation archive member")
        d,report=affiliation_records(*(contents[name] for name in required))
    elif dataset=="geographic":
        base="geographicalSettelments/"
        required=(base+"settlements.json",base+"combinedSettlements(PerfectMatch).json",base+"readMe.txt")
        if not set(required)<=set(contents):raise ValueError("Missing geographic archive member")
        if "clusteredVertices" not in contents[required[2]].decode("utf-8-sig"):
            raise ValueError("Geographic README no longer documents clusteredVertices")
        d,report=geographic_records(contents[required[0]],contents[required[1]],allow_redundant_singleton)
    else:raise ValueError("Unknown dataset")
    report["archive_members"]=members
    return d,report
