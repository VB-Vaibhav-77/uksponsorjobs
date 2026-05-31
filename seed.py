import server

def main():
    print("==============================================")
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
    print("\n[Testing] Crawling premium ATS feeds for live sponsorship jobs...")
    jobs_ok = server.run_jobs_sync()
    if jobs_ok:
        print("[Testing] [OK] Jobs sync completed successfully!")
    else:
        print("[Testing] [FAIL] Jobs sync failed.")
        
    print("\n==============================================")
    print("[Testing] Verification & seeding process complete!")

if __name__ == "__main__":
    main()
