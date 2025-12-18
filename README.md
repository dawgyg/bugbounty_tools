# bugbounty_tools
Collection of scripts and tools used during bug bounty work. This will be the location of my automation scripts created for my own personal use, and occassionally public released

# Contact: 
For questions, comments or request make a psot to my X account (not in DM) and I will do what I can to respond
https://x.com/thedawgyg

# Current tools:
- thc_recon.py - Script to use the THC Subdomain Lookup API to get subdomains for a given IP/IP Range/Root domain.
- thc_livecheck.py - Helper tool for thc_recon.py that will take the generated list of domains and find the active webservers on those hosts.


# Upcoming tools:
- xss_hunter.py - Site crawler, indexer, reflective parameter detection to aid in finding Reflected XSS (and additional vulns in the future)
- ssrf_hunter.py - Automated SSRF discovery tool. Will support Authenticated and Unauthenticated scans. Input single URL or file of hosts. More announced as work progresses.
