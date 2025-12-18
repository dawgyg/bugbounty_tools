#!/usr/bin/env python3

# A tool written to make use of the THC API to fetch domains/subdomains of a given IP address or root domain.
# Written by: Tommy DeVoss aka dawgyg (dawgyg@gmail.com / https://x.com/thedawgyg)
# toolname: thc_recon.py
# version: 1.1
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

def fetch_all(url_base, session, all_results, total_requests, errors, target, total_expected, rate_limit, mode_str, output_file):
    url = f"{url_base}?l=100"

    while url:
        total_requests[0] += 1
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 404:
                print(f"{Colors.GRAY}No records found for this endpoint (404) — skipping.{Colors.END}")
                break
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 404:
                print(f"{Colors.GRAY}No records found for this endpoint (404) — skipping.{Colors.END}")
                break
            else:
                print(f"\n[-] HTTP error: {e}")
                errors[0] += 1
                time.sleep(10)
                continue
        except requests.exceptions.RequestException as e:
            print(f"\n[-] Request failed: {e}")
            errors[0] += 1
            time.sleep(10)
            continue

        total_expected_new, rate_limit_new, next_page, results = parse_response(response.text)
        if total_expected_new is not None:
            total_expected[0] = total_expected_new
        if rate_limit_new is not None:
            rate_limit[0] = rate_limit_new

        added = 0
        for result in results:
            if result not in all_results:
                all_results.add(result)
                added += 1

        # Save progress after each page
        with open(output_file, 'w') as f:
            for result in sorted(all_results):
                f.write(result + "\n")

        # Update status — carriage return + clear to end of line
        print_status(target, len(all_results), total_expected[0], rate_limit[0], total_requests[0], mode_str)

        url = next_page
        sleep_time = get_sleep_time(rate_limit[0])
        time.sleep(sleep_time)

    return total_expected[0], rate_limit[0]

def print_status(target, fetched, total, rate_limit, requests_made, mode_str, resuming=False):
    remaining = total - fetched if total else 0
    total_str = total if total else "?"
    remaining_str = remaining if total else "?"
    resume_str = " (Resuming)" if resuming else ""
    
    status = (
        f"{Colors.CYAN}{Colors.BOLD}Target:{Colors.END} {Colors.WHITE}{target}{Colors.END}{resume_str}  |  "
        f"{Colors.GRAY}Mode:{Colors.END} {Colors.YELLOW}{mode_str}{Colors.END}  |  "
        f"{Colors.GRAY}Fetched:{Colors.END} {Colors.GREEN}{fetched}{Colors.END}/{Colors.GREEN}{total_str}{Colors.END}  "
        f"({Colors.GRAY}Remaining:{Colors.END} {Colors.GREEN}{remaining_str}{Colors.END})  |  "
        f"{Colors.GRAY}Rate Limit:{Colors.END} {Colors.YELLOW}{rate_limit}{Colors.END}  |  "
        f"{Colors.GRAY}Requests:{Colors.END} {Colors.WHITE}{requests_made}{Colors.END}"
    )
    # Carriage return + clear to end of line
    print(f"\r\033[K{status}", end="", flush=True)

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

def signal_handler(sig, frame, target, output_file):
    print(f"\n\n{Colors.YELLOW}Interrupted by user (Ctrl+C){Colors.END}")
    print(f"{Colors.CYAN}Target:{Colors.END} {target}")
    print(f"{Colors.GREEN}Fetched so far:{Colors.END} {len(all_results)}")
    print(f"{Colors.WHITE}Requests made:{Colors.END} {total_requests[0]}")
    print(f"{Colors.YELLOW}Errors:{Colors.END} {errors[0]}")
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
               f"  python3 thc_recon.py yahoo.com -o yahoo_cnames.txt --cnames-only\n"
               f"  python3 thc_recon.py yahoo.com -o yahoo_a_records.txt --no-cnames"
    )
    parser.add_argument("target", help="Domain (e.g., yahoo.com) or IP address")
    parser.add_argument("-o", "--output", required=True, help="Output text file to save results")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cnames-only", action="store_true", help="Fetch only CNAME records")
    group.add_argument("--no-cnames", action="store_true", help="Fetch only A/AAAA records (exclude CNAMEs)")

    args = parser.parse_args()

    global all_results, total_requests, errors

    if '.' in args.target and not args.target.replace('.', '').isdigit():
        domain = args.target
        mode = "subdomains"
    else:
        domain = args.target
        mode = "hosts on IP"

    print(BANNER)
    print(f"{Colors.WHITE}Starting fetch for {args.target} ({mode}) → {args.output}{Colors.END}\n")

    session = requests.Session()

    fetch_sb = not args.cnames_only
    fetch_cn = args.cnames_only or not args.no_cnames
    mode_str = "Both (A + CNAME)" if fetch_sb and fetch_cn else ("CNAMEs only" if args.cnames_only else "A/AAAA only")

    print(f"{Colors.YELLOW}Fetch mode: {mode_str}{Colors.END}\n")

    all_results = set()
    total_requests = [0]
    errors = [0]
    rate_limit = ["Unknown"]
    total_expected = [None]

    # Resume
    resuming = False
    if os.path.exists(args.output):
        with open(args.output, 'r') as f:
            existing = {line.strip() for line in f if line.strip()}
            all_results.update(existing)
            if existing:
                resuming = True
                print(f"{Colors.YELLOW}Resuming: {len(existing)} entries already in {args.output}{Colors.END}")

    fetched = len(all_results)

    print_status(args.target, fetched, total_expected[0], rate_limit[0], total_requests[0], mode_str, resuming)

    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, args.target, args.output))

    if fetch_sb:
        sb_url = f"https://ip.thc.org/sb/{domain}"
        print(f"{Colors.WHITE}Fetching A/AAAA subdomains...{Colors.END}")
        expected, rl = fetch_all(sb_url, session, all_results, total_requests, errors, args.target, total_expected, rate_limit, mode_str, args.output)
        if expected:
            total_expected[0] = expected
        rate_limit[0] = rl

    if fetch_cn:
        cn_url = f"https://ip.thc.org/cn/{domain}"
        print(f"{Colors.WHITE}Fetching CNAME records...{Colors.END}")
        expected, rl = fetch_all(cn_url, session, all_results, total_requests, errors, args.target, total_expected, rate_limit, mode_str, args.output)
        if expected and total_expected[0] is None:
            total_expected[0] = expected
        rate_limit[0] = rl

    # Final save
    with open(args.output, 'w') as f:
        for result in sorted(all_results):
            f.write(result + "\n")

    print("\n" + "="*80)
    print(f"{Colors.BOLD}SUMMARY{Colors.END}")
    print("="*80)
    print(f"{Colors.CYAN}Target:{Colors.END} {args.target}")
    print(f"{Colors.YELLOW}Mode:{Colors.END} {mode_str}")
    print(f"{Colors.GREEN}Total unique fetched:{Colors.END} {len(all_results)}")
    print(f"{Colors.WHITE}Total requests:{Colors.END} {total_requests[0]}")
    print(f"{Colors.YELLOW}Errors:{Colors.END} {errors[0]}")
    print(f"{Colors.WHITE}Saved to:{Colors.END} {args.output}")
    print("="*80)

if __name__ == "__main__":
    main()
