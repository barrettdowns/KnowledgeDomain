"""CLI entry point for the KD platform prototype."""
import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kd-platform")


def cmd_ingest(args):
    from src.ingest import ingest
    count = ingest(args.pdf, args.config, args.classification)
    logger.info(f"Ingestion complete: {count} chunks stored")


def cmd_ingest_naive(args):
    """Run the naive SkillSet (ss-doctrine-naive) over a directory of PDFs.

    Populates doctrine_naive_text_chunks (text_chunks projection of
    idx-doctrine-naive per catalog/doctrine-naive.yaml).
    """
    from src.ingest_naive import ingest_naive_corpus, get_naive_chunk_count

    def _emit(msg):
        logger.info(msg)

    stats = ingest_naive_corpus(args.data_dir, progress_cb=_emit)
    total = get_naive_chunk_count()
    logger.info(
        f"Naive ingestion complete: {stats['total_chunks']} chunks "
        f"across {stats['pdf_count']} PDFs. Total rows in "
        f"doctrine_naive_text_chunks: {total}"
    )


def cmd_lift(args):
    from src.lift import lift_batch
    total = 0
    while True:
        lifted = lift_batch(batch_size=args.batch_size, relift=args.relift)
        total += lifted
        if lifted < args.batch_size:
            break
    logger.info(f"Lifting complete: {total} chunks lifted")


def cmd_retrieve(args):
    from src.retrieve import retrieve
    filters = json.loads(args.filters) if args.filters else None
    results = retrieve(args.query, top_k=args.top_k, filters=filters)
    for r in results:
        score = f"{r['score']:.4f}" if r.get('score') else "N/A"
        mod = r.get('modality', '')
        para = r.get('paragraph_id', '')
        hier = r.get('hierarchy_path', [])
        if isinstance(hier, str):
            hier = json.loads(hier)
        path = " > ".join(hier) if hier else ""
        text = r['chunk_content'][:120].replace('\n', ' ')
        print(f"  [{score}] {para:6s} | {mod:12s} | {path}")
        print(f"           {text}...")
        print()


def cmd_benchmark(args):
    from src.benchmark import run_benchmark
    results = run_benchmark(args.qa)
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    for name, scores in results["summary"].items():
        print(f"\n  {name}:")
        print(f"    NDCG@10:     {scores['ndcg_10']:.4f}")
        print(f"    MRR:         {scores['mrr']:.4f}")
        print(f"    Precision@5: {scores['precision_5']:.4f}")
        print(f"    Questions:   {scores['question_count']}")
    print()


def cmd_compile_codex(args):
    from src.compile_codex import compile_codex_objects
    objects = compile_codex_objects(max_sections=args.max_sections)
    logger.info(f"Compiled {len(objects)} CODEX objects")


def cmd_export(args):
    from pathlib import Path
    import shutil
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy("migrations/V001__create_kd_doctrine.sql", out / "V001__create_kd_doctrine.sql")

    if Path("config/doctrine.yaml").exists():
        shutil.copy("config/doctrine.yaml", out / "doctrine.yaml")

    if Path("benchmarks/doctrine_qa.json").exists():
        shutil.copy("benchmarks/doctrine_qa.json", out / "doctrine_qa.json")

    from src.db import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) as cnt FROM kd_doctrine")
            cnt = cur.fetchone()["cnt"]
            cur.execute("""
                SELECT modality, count(*) as cnt FROM kd_doctrine GROUP BY modality ORDER BY cnt DESC
            """)
            dist = {r["modality"]: r["cnt"] for r in cur.fetchall()}
    finally:
        conn.close()

    manifest = {
        "kind": "KnowledgeDomain",
        "version": "1.0",
        "metadata": {
            "name": "doctrine",
            "display_name": "Military Doctrine",
            "reuse_tier": "flagship",
            "source_document": "ADP 3-0",
            "chunk_count": cnt,
            "modality_distribution": dist,
        },
        "schema": {"migration": "V001__create_kd_doctrine.sql"},
        "chunking": {"strategy": "atomic_doctrine_chunking"},
        "benchmarks": {"eval_dataset": "doctrine_qa.json"},
    }

    with open(out / "kd_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Exported KD package to {out}/")
    for p in sorted(out.iterdir()):
        logger.info(f"  {p.name}")


def main():
    parser = argparse.ArgumentParser(description="KD Platform Prototype")
    sub = parser.add_subparsers(dest="command")

    p_ingest = sub.add_parser("ingest", help="Ingest a doctrine PDF into kd_doctrine (moat SkillSet)")
    p_ingest.add_argument("--pdf", required=True, help="Path to PDF file")
    p_ingest.add_argument("--config", default=None, help="ADC config YAML")
    p_ingest.add_argument("--classification", default="UNCLASSIFIED")

    p_ingest_naive = sub.add_parser(
        "ingest-naive",
        help="Run naive SkillSet (ss-doctrine-naive) over a directory of PDFs into doctrine_naive_text_chunks",
    )
    p_ingest_naive.add_argument(
        "--data-dir", default="data", help="Directory containing the doctrine PDFs"
    )

    p_lift = sub.add_parser("lift", help="Run semantic lifting on unlifted chunks")
    p_lift.add_argument("--batch-size", type=int, default=20)
    p_lift.add_argument("--relift", action="store_true", help="Re-lift stale versions")

    p_retrieve = sub.add_parser("retrieve", help="Run a retrieval query")
    p_retrieve.add_argument("query", help="Search query")
    p_retrieve.add_argument("--top-k", type=int, default=10)
    p_retrieve.add_argument("--filters", default=None, help='JSON filters, e.g. \'{"modality":"REQUIREMENT"}\'')

    p_bench = sub.add_parser("benchmark", help="Run retrieval benchmarks")
    p_bench.add_argument("--qa", default="benchmarks/doctrine_qa.json")

    p_codex = sub.add_parser("compile-codex", help="Compile CODEX objects from doctrine chunks")
    p_codex.add_argument("--max-sections", type=int, default=8)

    p_export = sub.add_parser("export", help="Export KD package")
    p_export.add_argument("--output", default="doctrine-kd-package")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "ingest": cmd_ingest,
        "ingest-naive": cmd_ingest_naive,
        "lift": cmd_lift,
        "retrieve": cmd_retrieve,
        "benchmark": cmd_benchmark,
        "compile-codex": cmd_compile_codex,
        "export": cmd_export,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
