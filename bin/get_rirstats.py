"""
This program downloads Internet registry statistics from all five registries and produces CSV output.
The output comprises all IPv4 and IPv6 ranges. IPv4 ranges are reduced to complete CIDR ranges that represent the
potentially unaligned ranges in the registry. IPv6 ranges are CIDR-aligned as listed.

ASNs records are not useful yet because:
  1. AS numbers have 'holders', but that does not necessarily provide information about who or where the IP is used.
  2. IP records have opaque IDs, but the ID may be associated with one AS number, a range of AS numbers, or multiple
     ranges of AS numbers, and each component number may have a different 'holder'.
  3. There is no easy way to get AS number holders. ARIN has an incomplete text file and a (presumably complete) REST
     API. Efficiently accessing this API for Splunk queries is not feasible at this time.

For these reasons, the opaque ID is potentially useful to provide information about an IP range. To quote the Number
Resource Organization (NRO), the opaque ID is

    "an in-series identifier which uniquely identifies a single organisation [sic], an Internet number resource holder.

    "All records in the file with the same opaque-id are registered to the same resource holder.

    "The opaque-id is not guaranteed to be constant between versions of the file.

    "If the records are collated by type, opaque-id and date, records of the same type for the same opaque-id for the
    same date can be held to be a single assignment or allocation."
"""


import datetime
import inspect
import ipaddress
import logging
import os
import requests
import sys


RIRSTATS_URL = [
    'http://ftp.afrinic.net/stats/afrinic/delegated-afrinic-extended-latest',
    'http://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest',
    'http://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest',
    'http://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest',
    'http://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest'
    ]


log = logging.Logger


# define a logger for application messages
def new_logger(level):
    logger = logging.getLogger('TA-rirstats')
    logger.propagate = False
    logger.setLevel(level)
    splunk_home = os.getenv('SPLUNK_HOME')
    if splunk_home is not None:
        fh = logging.FileHandler(os.path.join(splunk_home, 'var', 'log', 'splunk', 'rirstats.log'))
    else:
        fh = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(filename)s %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


# format an error log message
def log_error(msg: str) -> None:
    # sys.stderr.write(f"{inspect.stack()[1][3]}(): {msg}\n")
    log.error(f"{inspect.stack()[1][3]}(): {msg}")


# format an informational log message
def log_info(msg: str) -> None:
    # sys.stderr.write(f"{msg}\n")
    log.info(f"{msg}")


# convert RIR date string to a date object
def get_date_from_yyyymmdd(text: str) -> datetime.date:
    if len(text) != 8 or not text.isdigit():
        return None
    y = int(text[0:4])
    m = int(text[4:6])
    d = int(text[6:8])
    try:
        result = datetime.date(y, m, d)
    except ValueError:
        return None
    return result


# parse a version record and ensure that the version is expected
def parse_version_record(row: str) -> dict:
    result = {}
    fields = row.split("|")

    try:
        version = float(fields[0])
    except ValueError:
        version = None
    """
    I assume -- without evidence -- that the format will be compatible if it is 2.x and that 3.0+ will break
    the field pattern or make the format otherwise impossible to parse.
    """
    if not version or 3.0 <= version < 2.0 or len(fields) != 7:
        log_error(f"expected a version 2.x row with seven fields, but got:\n  row = \"{row}\"")
        exit(1)

    try:
        result["version"] = version
        result["registry"] = fields[1]
        result["serial"] = int(fields[2])
        result["records"] = int(fields[3])
        result["startdate"] = get_date_from_yyyymmdd(fields[4])
        result["enddate"] = get_date_from_yyyymmdd(fields[5])
        result["UTCoffset"] = int(fields[6])
    except Exception as e:
        log_error(f"encountered exception {type(e)}: \"{e}\"\n  row = \"{row}\"")
        exit(1)

    return result


# parse a summary or detail record
def parse_record(row: str) -> dict:
    result = {}
    fields = row.split("|")
    if len(fields) < 6:
        log_error(f"row has fewer than six fields; ignoring:\n  row = \"{row}\"")
        return None

    if fields[5] == "summary":
        # summary records are unused, so it is okay to ignore a parsing error for now
        try:
            result["registry"] = fields[0]
            result["type"] = fields[2]
            result["count"] = int(fields[4])
            result["summary"] = fields[5]  # should be 'summary'
        except Exception as e:
            log_error(f"encountered exception {type(e)}: \"{e}\"\n  row = \"{row}\"")
            return None
    else:
        try:
            result["registry"] = fields[0]
            result["cc"] = fields[1]
            if fields[2] == "asn":  # maybe useful in the future
                result["type"] = fields[2]
                result["start"] = int(fields[3])
                result["value"] = int(fields[4])
            elif fields[2] == "ipv4":
                result["type"] = fields[2]
                result["start"] = ipaddress.IPv4Address(fields[3])
                result["value"] = int(fields[4])
            elif fields[2] == "ipv6":
                result["type"] = fields[2]
                result["start"] = ipaddress.IPv6Address(fields[3])
                result["value"] = int(fields[4])
            result["date"] = get_date_from_yyyymmdd(fields[5])
            result["status"] = fields[6]
            if len(fields) >= 8:
                result["opaque_id"] = fields[7]
            else:
                result["opaque_id"] = None
        except Exception as e:
            log_error(f"encountered exception {type(e)}: \"{e}\"\n  row = \"{row}\"")
            exit(1)

    if "type" in result and result["type"] in ("ipv4", "ipv6"):
        return result
    else:
        return None


# get a stats list from a URL
def get_stats_list_from_url(url: str) -> list:
    result = []
    log_info(f"starting download of RIR stats from {url}")
    try:
        r = requests.get(url)
    except Exception as e:
        log_error(f"encountered exception {type(e)}: \"{e}\"")
        exit(1)
    if r.status_code != 200:
        log_error(f"download of {url} failed with status {r.status_code}")
        exit(1)
    for row in r.text.splitlines():
        row = row.strip()
        if row[0] == "#":  # skip comment
            continue
        elif len(row) == 0:  # skip blank line
            continue
        else:
            result.append(row.rstrip("\n"))
    log_info(f"completed download of RIR stats; got {len(result)} records")
    return result


# parse a RIR stats record list
def parse_stats_list(stats_list: list) -> list:
    result = []
    v = None
    count_version = 0
    count_summary = 0
    count_detail = 0
    for item in stats_list:
        if not v:  # the first real row must be a version record
            v = parse_version_record(item)
            count_version += 1
            continue
        d = parse_record(item)
        if d:
            if "summary" in d:  # count but don't keep summary record
                count_summary += 1
            else:  # count and append detail record
                count_detail += 1
                result.append(d)
    # log_info(f"version={v['version']} detail_expected={v['records']} version_read={count_version} "
    #          f"summary_read={count_summary} detail_read={count_detail}")
    return result


# make a CSV from the parsed RIR stats list
def write_intermediate_stats_to_csv(ranges: list) -> None:
    log_info("started CSV version of RIR stats")
    output_count = 0
    sys.stdout.write("type,subnet,registry,country,date,status,reg_id\n")
    sorted_ranges = sorted([i for i in ranges if type(i["start"]) == ipaddress.IPv4Address], key=lambda k: k["start"])
    sorted_ranges.extend(
        sorted([i for i in ranges if type(i["start"]) == ipaddress.IPv6Address], key=lambda k: k["start"])
    )
    for r in sorted_ranges:
        if r["type"] == "ipv4":
            first_address = r["start"]
            last_address = first_address + (r["value"] - 1)
            # a v4 range can be unaligned with one CIDR block, so convert to as many CIDR blocks as necessary
            for rr in ipaddress.summarize_address_range(first_address, last_address):
                sys.stdout.write(f"{r['type']},"
                                 f"{rr},"
                                 f"{r['registry']},"
                                 f"{r['cc']},"
                                 f"{r['date'] if r['date'] else ''},"
                                 f"{r['status']},"
                                 f"{r['opaque_id'] if r['opaque_id'] else ''}\n")
                output_count += 1
        elif r["type"] == "ipv6":
            sys.stdout.write(f"{r['type']},"
                             f"{r['start']}/{r['value']},"
                             f"{r['registry']},"
                             f"{r['cc']},"
                             f"{r['date'] if r['date'] else ''},"
                             f"{r['status']},"
                             f"{r['opaque_id'] if r['opaque_id'] else ''}\n")
            output_count += 1
    log_info(f"completed CSV version of RIR stats; wrote {output_count} records")


# start here
def main():
    global log
    # create logger
    log = new_logger(logging.INFO)
    # get and parse RIR stats
    ranges = []
    for url in RIRSTATS_URL:
        stats_list = get_stats_list_from_url(url)  # download stats
        ranges.extend(parse_stats_list(stats_list))  # compile the stats list
        stats_list.clear()
    # write CSV to stdout
    write_intermediate_stats_to_csv(ranges)  # write the CSV to stdout
    exit(0)


if __name__ == "__main__":
    main()
