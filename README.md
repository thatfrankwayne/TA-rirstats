![icon](static/appIcon_2x.png)

# TA-rirstats

A Regional Internet Registry Consolidated Extended Statistics Tables Add-on for Splunk.

## Purpose

This TA creates and updates a lookup containing all the network ranges
available, allocated, assigned, or reserved by the five regional
Internet registries (RIR). Splunk searches can use this lookup to identify the
subnet associated with any public IP address, as well as an ID that can be used
to find all ranges associated with a particular registration.

### Example 1

Assume that a pfsense firewall named "pfsense" sends syslog to Splunk to an 
index named "syslog". We are interested in external traffic hitting our
firewall on non-HTTP ports, which probably indicate port scans since we do not
advertise other services for this IP (1.2.3.4 in this example).

```
index=syslog host=pfsense dest_ip=1.2.3.4 NOT dest_port IN (80, 443)
```

Extant extractions produce CIM fields like `src_ip`, `dest_ip`, and
`dest_port`.

We can include RIR subnet, registration ID (opaque-id in RIR terminology),
status, and the registration country for the `src_ip` by adding this lookup:

    index=syslog host=pfsense dest_ip=1.2.3.4 NOT dest_port IN (80, 443)
    | lookup rirstats subnet AS src_ip OUTPUT subnet AS src_subnet reg_id AS src_reg_id status AS src_status country AS src_country registry AS src_registry

Our event detail now includes more information about the `src_ip`:

```
.
.
src            141.98.11.145
src_country    LT
src_ip         141.98.11.145	
src_port       32829	
src_reg_id     6de0db3c-65bd-4fbd-9031-a782e094d4f5	
src_registry   ripencc	
src_status     allocated	
src_subnet     141.98.8.0/22
.
.
```

The `src_country`, `src_reg_id`, `src_registry`, `src_status`, and `src_subnet`
are all fields from the lookup. The data provides that the source subnet
(141.98.8.0/22) is allocated to a Latvian holder by the RIPE NCC registry.
Furthermore, we can use the registration ID to find all the subnets registered
to that entity:

```
| inputlookup rirstats
| where registry=="ripencc" and reg_id=="6de0db3c-65bd-4fbd-9031-a782e094d4f5"
```

This produces a list containing two registrations:

```
country date        reg_id                               registry status    subnet         type
------- ----        ------                               -------- ------    ------         ----
LT      2019-01-10  6de0db3c-65bd-4fbd-9031-a782e094d4f5 ripencc  allocated 141.98.8.0/22  ipv4
LT      2023-05-16  6de0db3c-65bd-4fbd-9031-a782e094d4f5 ripencc  allocated 2a0f:8a40::/29 ipv6
```

### Example 2

Using the assumptions from Example 1, we want to know that top five *subnets*
on the Internet that are responsible for the most unsolicited traffic and where
the holders are registered. We run this search for events over the last 24
hours:

```
index=syslog host=pfsense dest_ip=1.2.3.4 NOT dest_port IN (80, 443)
| lookup rirstats subnet AS src_ip OUTPUT subnet AS src_subnet reg_id AS src_reg_id status AS src_status country AS src_country registry AS src_registry
| stats count dc(src_ip) AS src_hosts dc(dest_port) AS dest_ports first(src_country) AS src_country first(src_registry) AS src_registry first(src_reg_id) AS src_reg_id BY src_subnet
| sort 0 -count
```

The results provide us with several data:

```
src_subnet       count src_hosts dest_ports src_country src_registry src_reg_id
----------       ----- --------- ---------- ----------- ------------ ----------
79.124.0.0/18    1725  14        1722       BG          ripencc      15529f71-b7f4-4452-9b67-65a257a2ab72
91.148.188.0/22  570   4         570        BG          ripencc      15529f71-b7f4-4452-9b67-65a257a2ab72
92.63.196.0/22   464   3         464        RU          ripencc      da91a251-3fe5-4df4-9302-41a156df95cb
165.154.224.0/19 319   1         292        SG          apnic        A9154340
79.110.62.0/23   276   8         229        BG          ripencc      a1f45994-15b5-4e65-ba5a-32a664039898
```

The top scanners were in Bulgaria, Russia and Singapore. The top source range
produced traffic from 14 distinct host addresses and hit 1722 different ports
on our firewall. Interestingly, the top two ranges are registered to the same
Bulgarian holder (based on the opaque-id provided in src_reg_id).

## Prerequisites and Dependencies

The TA should be installed only on search heads. It can be deployed to a search
head cluster via a deployer. It will run on Linux or Windows.

Once per week (by default), the TA runs a scheduled search named `TA-rirstats
Refresh Lookup` that refreshes the lookup table with the latest data from the
five registries. This functionality requires Splunk 8.0 or later (i.e. Python
3). The search heads should have Internet web access for this to work.

## Developer

The TA was developed by Frank Wayne.

## Support Contact

Check the [PDF documentation](https://github.com/thatfrankwayne/TA-rirstats/blob/main/readme/TA-rirstats-3.pdf)
for installation and other information.

Contact [the developer](mailto:frank.wayne@northwestern.edu?subject=TA-rirstats)
with questions, bug reports or change requests. You can also refer or
contribute to the [GitHub repository](https://github.com/thatfrankwayne/TA-rirstats).
