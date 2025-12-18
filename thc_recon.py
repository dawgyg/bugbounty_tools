# A tool written to make use of the THC API to fetch domains/subdomains of a given IP address or root domain.
# Written by: Tommy DeVoss aka dawgyg (dawgyg@gmail.com / https://x.com/thedawgyg)
# toolname: thc_recon.py
# version: 1.0
#
# Features:
# - Fetch all hosts for a provided IP or root domain
# - Auto resume if interupted (running same command will pick up where it left off)
# - Monitors rate limit to prevent failures, will sleep to allow for RL to refresh as needed
#
# Feature Requests: post them to my X account: https://x.com/thedawgyg

import requests
import argparse
import sys
import time
import re
import os
import signal

# ANSI colors
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    RED = '\033[91m'   
    END = '\033[0m'

BANNER = f"{Colors.CYAN}{Colors.BOLD}*** THC Recon - by Tommy DeVoss (dawgyg) https://x.com/thedawgyg ***{Colors.END}\n"

def aggressive_strip_ansi(s):
    if not s:
        return None
    s = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', s)
    s = re.sub(r'\x1B[@-Z\\-_][0-?]*[ -/]*[@-~]', '', s)
    s = re.sub(r'\x1B\([AB0-2]', '', s)
    return s.strip()

def parse_response(text):
    total_entries = None
    rate_limit = None
    next_page_candidate = None
    results = []

    for raw_line in text.splitlines():
        line = aggressive_strip_ansi(raw_line)

        if not line:
            continue

        if line.startswith(";;Entries:"):
            parts = line.split("/")
            if len(parts) >= 2:
                try:
                    total_entries = int(parts[1].split()[0])
                except:
                    pass
        elif line.startswith(";;Rate Limit:"):
            match = re.search(r'You can make (\d+)', line)
            if match:
                rate_limit = int(match.group(1))
        elif line.startswith(";;Next Page:"):
            candidate = line.split(":", 1)[1] if ":" in line else line
            next_page_candidate = aggressive_strip_ansi(candidate)
        elif not line.startswith(";;"):
            clean_result = aggressive_strip_ansi(raw_line).strip()
            if clean_result:
                results.append(clean_result)

    next_page = None
    if next_page_candidate and next_page_candidate.startswith("https://ip.thc.org/"):
        next_page = next_page_candidate

    return total_entries, rate_limit, next_page, results

def print_status(target, fetched, total, rate_limit, requests_made, resuming=False):
    remaining = total - fetched if total else 0
    total_str = total if total else "?"
    remaining_str = remaining if total else "?"
    resume_str = " (Resuming)" if resuming else ""
    
    status = (
        f"{Colors.CYAN}{Colors.BOLD}Target:{Colors.END} {Colors.WHITE}{target}{Colors.END}{resume_str}  |  "
        f"{Colors.GRAY}Fetched:{Colors.END} {Colors.GREEN}{fetched}{Colors.END}/{Colors.GREEN}{total_str}{Colors.END}  "
        f"({Colors.GRAY}Remaining:{Colors.END} {Colors.GREEN}{remaining_str}{Colors.END})  |  "
        f"{Colors.GRAY}Rate Limit:{Colors.END} {Colors.YELLOW}{rate_limit}{Colors.END}  |  "
        f"{Colors.GRAY}Requests:{Colors.END} {Colors.WHITE}{requests_made}{Colors.END}"
    )
    print(f"\r{status}          ", end="", flush=True)

def get_sleep_time(rate_limit_remaining):
    if rate_limit_remaining is None or rate_limit_remaining == "Unknown":
        return 2.1
    rl = int(rate_limit_remaining)
    if rl >= 50:
        return 0.1
    elif rl >= 20:
        return 0.5
    elif rl >= 10:
        return 1.0
    else:
        return 2.2 - (rl * 0.1)

def signal_handler(sig, frame, target, fetched, total, requests, errors, output_file):
    print(f"\n\n{Colors.YELLOW}Interrupted by user (Ctrl+C){Colors.END}")
    print(f"{Colors.CYAN}Target:{Colors.END} {target}")
    print(f"{Colors.GREEN}Fetched so far:{Colors.END} {fetched}")
    print(f"{Colors.WHITE}Requests made:{Colors.END} {requests}")
    print(f"{Colors.YELLOW}Errors:{Colors.END} {errors}")
    print(f"{Colors.WHITE}Progress saved to:{Colors.END} {output_file}")
    print(f"{Colors.RED}{Colors.BOLD}Run the same command again to resume.{Colors.END}")
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description=f"{Colors.CYAN}{Colors.BOLD}THC Recon{Colors.END} - Fetch all subdomains or hosts from ip.thc.org API\n"
                    f"{Colors.WHITE}by Tommy DeVoss (dawgyg) https://x.com/thedawgyg{Colors.END}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"{Colors.CYAN}Examples:{Colors.END}\n"
               f"  python3 thc_recon.py yahoo.com -o yahoo_subdomains.txt\n"
               f"  python3 thc_recon.py 98.136.96.1 -o yahoo_hosts.txt",
        add_help=False
    )
    parser.add_argument("target", nargs='?', help="Domain (e.g., yahoo.com) or IP address")
    parser.add_argument("-o", "--output", help="Output text file to save results")
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

    try:
        args = parser.parse_args()
    except:
        parser.print_help()
        sys.exit(1)

    if not args.target or not args.output:
        parser.print_help()
        sys.exit(1)

    if '.' in args.target and not args.target.replace('.', '').isdigit():
        base_path = f"sb/{args.target}"
        mode = "subdomains"
    else:
        base_path = args.target
        mode = "hosts on IP"

    initial_url = f"https://ip.thc.org/{base_path}?l=100"

    print(BANNER)
    print(f"{Colors.WHITE}Starting fetch for {args.target} ({mode}) → {args.output}{Colors.END}\n")

    session = requests.Session()

    # Resume support
    already_fetched = 0
    resuming = False
    if os.path.exists(args.output):
        with open(args.output, 'r') as f:
            already_fetched = sum(1 for line in f if line.strip())
        if already_fetched > 0:
            resuming = True
            print(f"{Colors.YELLOW}Resuming: {already_fetched} entries already in {args.output}{Colors.END}")

    url = initial_url
    total_fetched = already_fetched
    total_requests = 0
    errors = 0
    total_expected = None
    rate_limit = "Unknown"

    print_status(args.target, total_fetched, total_expected, rate_limit, total_requests, resuming=resuming)

    # Set up graceful Ctrl+C handler
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, args.target, total_fetched, total_expected, total_requests, errors, args.output))

    file_mode = 'a' if resuming else 'w'
    with open(args.output, file_mode) as f:
        # Skip pages if resuming
        if resuming:
            skipped_pages = 0
            while url and total_fetched >= 100:
                total_requests += 1
                try:
                    response = session.get(url, timeout=30)
                    response.raise_for_status()
                except requests.exceptions.RequestException as e:
                    print(f"\n[-] Request failed during skip: {e}")
                    errors += 1
                    time.sleep(10)
                    continue

                total_expected_new, rate_limit_new, next_page, results = parse_response(response.text)
                if total_expected_new is not None:
                    total_expected = total_expected_new
                if rate_limit_new is not None:
                    rate_limit = rate_limit_new

                fetched_this_page = len(results)
                if fetched_this_page < 100:
                    url = None
                    break

                total_fetched -= fetched_this_page
                skipped_pages += 1
                print_status(args.target, already_fetched + skipped_pages * 100, total_expected, rate_limit, total_requests, resuming=True)

                url = next_page
                sleep_time = get_sleep_time(rate_limit)
                time.sleep(sleep_time)

            total_fetched = already_fetched

        # Main loop
        while url:
            total_requests += 1
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"\n[-] Request failed: {e}")
                errors += 1
                time.sleep(10)
                print_status(args.target, total_fetched, total_expected, rate_limit, total_requests, resuming=resuming)
                continue

            total_expected_new, rate_limit_new, next_page, results = parse_response(response.text)
            if total_expected_new is not None:
                total_expected = total_expected_new
            if rate_limit_new is not None:
                rate_limit = rate_limit_new

            fetched_this_page = len(results)
            total_fetched += fetched_this_page

            for result in results:
                f.write(result + "\n")

            print_status(args.target, total_fetched, total_expected, rate_limit, total_requests, resuming=resuming)

            url = next_page

            sleep_time = get_sleep_time(rate_limit)
            time.sleep(sleep_time)

    print("\n" + "="*80)
    print(f"{Colors.BOLD}SUMMARY{Colors.END}")
    print("="*80)
    print(f"{Colors.CYAN}Target:{Colors.END} {args.target}")
    print(f"{Colors.GREEN}Total fetched:{Colors.END} {total_fetched}")
    print(f"{Colors.WHITE}Total requests:{Colors.END} {total_requests}")
    print(f"{Colors.YELLOW}Errors:{Colors.END} {errors}")
    print(f"{Colors.WHITE}Saved to:{Colors.END} {args.output}")
    print("="*80)

if __name__ == "__main__":
    main()
