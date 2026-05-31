import server

def main():
    print("==============================================")
    print("Imported server from:", getattr(server, "__file__", "Unknown (Built-in)"))
    
    # 1. Initialize SQLite Database Schema
    print("[Testing] Initializing SQLite jobs.db database...")
    server.db_init()
    
    # 2. Run Sponsors Register Sync
    print("\n[Testing] Fetching and parsing GOV.UK Sponsorship register...")
    sponsors_ok = server.run_sponsors_sync()
    if sponsors_ok:
        print("[Testing] [OK] Sponsors register synced successfully!")
    else:
        print("[Testing] [FAIL] Sponsors register sync failed.")
        return
        
    # 3. Run Live Jobs Sync (Greenhouse & Lever APIs)
    print("\n[Testing] Crawling premium website career pages in background batches...")
    jobs_count = server.auto_crawl_sponsor_batch()
    print(f"[Testing] [OK] Batch completed! Crawled and indexed {jobs_count} live jobs.")
        
    print("\n==============================================")
    print("[Testing] Verification & seeding process complete!")

if __name__ == "__main__":
    main()
