import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def backfill():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["test_database"]
    
    # Find all opus46 matches that have 'winner' but no 'winner_id'
    cursor = db.validation_matches.find(
        {"content_mode": {"$regex": ":opus46"}, "winner": {"$exists": True}, "winner_id": {"$exists": False}},
        {"_id": 1, "paper1_id": 1, "paper2_id": 1, "winner": 1}
    )
    
    fixed = 0
    async for m in cursor:
        winner_key = m.get("winner", "")
        if winner_key == "paper1":
            winner_id = m["paper1_id"]
        elif winner_key == "paper2":
            winner_id = m["paper2_id"]
        else:
            continue
        
        await db.validation_matches.update_one(
            {"_id": m["_id"]},
            {"$set": {"winner_id": winner_id}}
        )
        fixed += 1
    
    print(f"Backfilled winner_id for {fixed} opus46 matches")
    
    # Verify
    datasets = ["iclr-codegen", "iclr-fairness", "iclr-llm", "iclr-molecules",
                 "iclr-optimization", "iclr-ot", "iclr-pdes", "iclr-protein"]
    for ds in datasets:
        with_wid = await db.validation_matches.count_documents({
            "dataset_id": ds,
            "content_mode": "abstract_plus_summary:opus46",
            "winner_id": {"$exists": True}
        })
        total = await db.validation_matches.count_documents({
            "dataset_id": ds,
            "content_mode": "abstract_plus_summary:opus46"
        })
        if total > 0:
            print(f"  {ds}: {with_wid}/{total} now have winner_id")
    
    client.close()

asyncio.run(backfill())
