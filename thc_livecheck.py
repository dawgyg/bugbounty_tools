# Tool that will take the output from the thc_recon.py script, and will find which hosts
# resolve, which ones resolve to internal / public ips, and find which are running webservers
# on some of the more common web server ports. Also has some other small features mentioned below.
# 
# Disclaimer: Only use this tool for activity which you are authorized to do so. I make no gauruntees 
# as to the accuracy of the results of this tool.
#
# Name: thc_livecheck.py
# Version: 1.0
# Author: Tommy DeVoss (dawgyg)
# Contact: https://x.com/thedawgyg
#
# Current Features:
# - Finds valid hosts
# - Sorts internal vs external
# - Attempts to find webservers running on common ports
# - Attempts to fingerprint discovered web servers
# - Grabs title of root page for any discovered webserver
# - Screenshots root page on each discovered webserver

import argparse
import sys
import os
import socket
import time
import queue
import threading
import signal
import requests
import urllib3
from pathlib import Path
from playwright.sync_api import sync_playwright

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'  # Added
    END = '\033[0m'

BANNER = f"{Colors.CYAN}{Colors.BOLD}*** THC LiveCheck - by Tommy DeVoss (dawgyg) https://x.com/thedawgyg ***{Colors.END}\n"

WEB_PORTS = [80, 443, 8080, 8443, 8000, 3000, 8081, 8444]

interrupted = False
status_lock = threading.Lock()

def is_private_ip(ip):
    try:
        octets = list(map(int, ip.split('.')))
        if octets[0] == 10:
            return True
        if octets[0] == 172 and 16 <= octets[1] <= 31:
            return True
        if octets[0] == 192 and octets[1] == 168:
            return True
    except:
        pass
    return False

def take_screenshot(host, port, screenshot_dir, screenshot_counter):
    if interrupted:
        return
    scheme = "https" if port in [443, 8443, 8444] else "http"
    url = f"{scheme}://{host}:{port}/"
    filename = screenshot_dir / f"{host}.{port}.png"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000, wait_until="networkidle")
            page.screenshot(path=str(filename), full_page=True)
            browser.close()
        with status_lock:
            screenshot_counter[0] += 1
            print_status(scanned_counter[0], total, found_counter[0], len(internal_list), screenshot_counter[0])
    except:
        pass

def worker(task_queue, internal_list, titles_list, fingerprint_list, live_results, total, screenshot_dir, screenshot_counter):
    while True:
        if interrupted:
            return
        try:
            host = task_queue.get(timeout=1)
        except queue.Empty:
            return

        open_ports = []
        resolved_ip = None
        try:
            resolved_ip = socket.gethostbyname(host)
            if is_private_ip(resolved_ip):
                with status_lock:
                    internal_list.append(f"{host} → {resolved_ip}")

            for port in WEB_PORTS:
                if interrupted:
                    break
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    open_ports.append(port)
        except (socket.gaierror, OSError):
            pass

        with status_lock:
            scanned_counter[0] += 1
            if open_ports:
                found_counter[0] += 1
            print_status(scanned_counter[0], total, found_counter[0], len(internal_list), screenshot_counter[0])

        if open_ports:
            open_ports.sort()
            port_str = ", ".join(map(str, open_ports))
            live_results.append(f"{host} web servers: {port_str}")

            for port in open_ports:
                if interrupted:
                    break
                scheme = "https" if port in [443, 8443, 8444] else "http"
                url = f"{scheme}://{host}:{port}/"
                try:
                    r = requests.get(url, timeout=5, verify=False, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                    server = r.headers.get("Server", "Unknown")
                    powered_by = r.headers.get("X-Powered-By", "")
                    server_str = server
                    if powered_by:
                        server_str += f" ({powered_by})"

                    title = "No title"
                    if "<title" in r.text.lower():
                        start = r.text.lower().find("<title")
                        if start != -1:
                            start = r.text.find(">", start) + 1
                            end = r.text.find("</title>", start)
                            if end != -1:
                                title = r.text[start:end].strip().replace("\n", " ").replace("\r", " ")

                    if titles_list is not None:
                        titles_list.append(f"{host} Port: {port} Root Page Title: {title}")

                    if fingerprint_list is not None:
                        fingerprint_list.append(f"{host} Port: {port} Server: {server_str}")

                    if screenshot_dir:
                        take_screenshot(host, port, screenshot_dir, screenshot_counter)

                except:
                    pass

        task_queue.task_done()

def print_status(scanned, total, found, internal, screenshots):
    screenshot_str = f"  |  {Colors.MAGENTA}Screenshots: {screenshots}{Colors.END}"
    status = (
        f"{Colors.CYAN}{Colors.BOLD}Scanning:{Colors.END} {Colors.WHITE}{scanned}/{total}{Colors.END}  |  "
        f"{Colors.GRAY}Live web servers:{Colors.END} {Colors.GREEN}{found}{Colors.END}  |  "
        f"{Colors.YELLOW}Internal IPs: {internal}{Colors.END}{screenshot_str}"
    )
    print(f"\r{status}          ", end="", flush=True)

def sigint_handler(total_targets, output_dir):
    global interrupted
    interrupted = True
    print(f"\n\n{Colors.YELLOW}Interrupted by user (Ctrl+C){Colors.END}")
    print(f"{Colors.WHITE}Closing threads{Colors.END}")
    print_status(scanned_counter[0], total_targets, found_counter[0], len(internal_list), screenshot_counter[0])
    print(f"\n{Colors.CYAN}Scanned:{Colors.END} {scanned_counter[0]}/{total_targets}")
    print(f"{Colors.GREEN}Live web servers found:{Colors.END} {found_counter[0]}")
    print(f"{Colors.YELLOW}Internal IPs detected:{Colors.END} {len(internal_list)}")
    print(f"{Colors.MAGENTA}Screenshots taken:{Colors.END} {screenshot_counter[0]}")
    print(f"{Colors.WHITE}Partial results saved to: ./{output_dir}/{Colors.END}")
    print(f"{Colors.RED}{Colors.BOLD}Run the same command again to continue scanning.{Colors.END}")

def main():
    global interrupted, total, scanned_counter, found_counter, internal_list, screenshot_counter, screenshot_dir

    parser = argparse.ArgumentParser(
        description=f"{Colors.CYAN}{Colors.BOLD}THC LiveCheck{Colors.END} - Check subdomains for open web ports\n"
                    f"{Colors.WHITE}by Tommy DeVoss (dawgyg) https://x.com/thedawgyg{Colors.END}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"{Colors.CYAN}Examples:{Colors.END}\n"
               f"  python3 thc_livecheck.py -i paypal.com.txt -o paypal_live.txt\n"
               f"  python3 thc_livecheck.py -i paypal.com.txt -o paypal_live.txt -t titles.txt -f fingerprint.txt -s"
    )
    parser.add_argument("-i", "--input", required=True, help="Input file with subdomains (one per line)")
    parser.add_argument("-o", "--output", required=True, help="Base name for output files (e.g., paypal_live.txt)")
    parser.add_argument("-t", "--titles", help="Output file for page titles (optional)")
    parser.add_argument("-f", "--fingerprint", help="Output file for server fingerprinting (optional)")
    parser.add_argument("-s", "--screenshots", action="store_true", help="Take screenshots of open web servers")
    parser.add_argument("--threads", type=int, default=100, help="Number of threads (default: 100)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"{Colors.RED}[-] Input file not found: {args.input}{Colors.END}")
        sys.exit(1)

    with open(args.input, 'r') as f:
        subdomains = [line.strip() for line in f if line.strip()]

    total = len(subdomains)
    if total == 0:
        print(f"{Colors.YELLOW}[-] No subdomains found in input file.{Colors.END}")
        sys.exit(0)

    # Output directory
    domain_guess = args.output.split('.')[0] if '.' in args.output else "results"
    output_dir = Path(domain_guess)
    output_dir.mkdir(exist_ok=True)
    screenshot_dir = None
    screenshot_counter = [0]
    if args.screenshots:
        screenshot_dir = output_dir / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)
        print(f"{Colors.WHITE}Screenshots will be saved to: {screenshot_dir}{Colors.END}")

    live_output = output_dir / args.output
    titles_output = output_dir / args.titles if args.titles else None
    fingerprint_output = output_dir / args.fingerprint if args.fingerprint else None

    print(BANNER)
    print(f"{Colors.WHITE}Loaded {total} subdomains from {args.input}{Colors.END}")
    print(f"{Colors.WHITE}All results will be saved in ./{domain_guess}/{Colors.END}")
    print(f"{Colors.WHITE}Scanning ports {WEB_PORTS} using {args.threads} threads...{Colors.END}")
    if args.titles:
        print(f"{Colors.WHITE}Grabbing page titles → {titles_output}{Colors.END}")
    if args.fingerprint:
        print(f"{Colors.WHITE}Fingerprinting servers → {fingerprint_output}{Colors.END}")
    print()

    scanned_counter = [0]
    found_counter = [0]
    internal_list = []
    titles_list = [] if args.titles else None
    fingerprint_list = [] if args.fingerprint else None
    live_results = []

    print_status(0, total, 0, 0, 0)

    task_queue = queue.Queue()
    for host in subdomains:
        task_queue.put(host)

    signal.signal(signal.SIGINT, lambda sig, frame: sigint_handler(total, domain_guess))

    threads = []
    for _ in range(args.threads):
        t = threading.Thread(target=worker, args=(task_queue, internal_list, titles_list, fingerprint_list, live_results, total, screenshot_dir, screenshot_counter))
        t.start()
        threads.append(t)

    while not interrupted and any(t.is_alive() for t in threads):
        time.sleep(0.1)

    interrupted = True

    for t in threads:
        t.join(timeout=1)

    # Save results
    with open(live_output, 'w') as f:
        for line in live_results:
            f.write(line + "\n")

    internal_file = output_dir / f"{domain_guess}_internal.txt"
    if internal_list:
        with open(internal_file, 'w') as f:
            for line in internal_list:
                f.write(line + "\n")

    if args.titles and titles_list:
        with open(titles_output, 'w') as f:
            for line in titles_list:
                f.write(line + "\n")

    if args.fingerprint and fingerprint_list:
        with open(fingerprint_output, 'w') as f:
            for line in fingerprint_list:
                f.write(line + "\n")

    if not interrupted:
        print(f"\n\n{Colors.BOLD}SCAN COMPLETE{Colors.END}")
        print(f"{Colors.GREEN}Live web servers found: {len(live_results)}{Colors.END}")
        print(f"{Colors.MAGENTA}Screenshots taken: {screenshot_counter[0]}{Colors.END}")
        print(f"{Colors.WHITE}Results saved to: ./{domain_guess}/{Colors.END}")
        if len(internal_list) > 0:
            print(f"{Colors.YELLOW}Internal IPs found: {len(internal_list)}{Colors.END}")
            print(f"{Colors.WHITE}Internal hosts saved to: {internal_file}{Colors.END}")
        if args.titles:
            print(f"{Colors.WHITE}Titles saved to: {titles_output}{Colors.END}")
        if args.fingerprint:
            print(f"{Colors.WHITE}Fingerprints saved to: {fingerprint_output}{Colors.END}")
        if args.screenshots:
            print(f"{Colors.WHITE}Screenshots saved to: {screenshot_dir}{Colors.END}")

if __name__ == "__main__":
    main()
