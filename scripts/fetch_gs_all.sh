#!/bin/bash
# Full Google Scholar scraper for COCHE papers
# Uses curl + SOCKS5 proxy (trojan), saves each page to file, then parses

PROXY="--socks5 127.0.0.1:1080"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
QUERY="Hong+Kong+Centre+Cerebro-cardiovascular+Health+Engineering"
OUTDIR="/tmp/gs_pages"
mkdir -p "$OUTDIR"

echo "Fetching Google Scholar pages..."
for start in $(seq 0 10 490); do
    PAGE=$((start / 10 + 1))
    OUTFILE="$OUTDIR/page_$(printf '%03d' $start).html"
    
    if [ -f "$OUTFILE" ]; then
        echo "  Page $PAGE (start=$start): already fetched, skipping"
        continue
    fi
    
    curl -s --max-time 25 $PROXY \
        -H "User-Agent: $UA" \
        -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" \
        -H "Accept-Language: en-US,en;q=0.9" \
        "https://scholar.google.com/scholar?q=$QUERY&hl=en&as_sdt=0,5&num=10&start=$start" \
        -o "$OUTFILE" 2>/dev/null
    
    SIZE=$(wc -c < "$OUTFILE")
    if [ "$SIZE" -lt 1000 ]; then
        echo "  Page $PAGE (start=$start): BLOCKED (${SIZE} bytes)"
        rm "$OUTFILE"
        # Wait and retry
        sleep 15
        curl -s --max-time 25 $PROXY \
            -H "User-Agent: $UA" \
            -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" \
            -H "Accept-Language: en-US,en;q=0.9" \
            "https://scholar.google.com/scholar?q=$QUERY&hl=en&as_sdt=0,5&num=10&start=$start" \
            -o "$OUTFILE" 2>/dev/null
        SIZE=$(wc -c < "$OUTFILE")
        if [ "$SIZE" -lt 1000 ]; then
            echo "  Page $PAGE: still blocked, skipping."
            rm "$OUTFILE"
            continue
        fi
    fi
    
    echo "  Page $PAGE (start=$start): ${SIZE} bytes"
    sleep 2  # Rate limit delay
done

echo ""
echo "Done fetching. Pages saved to $OUTDIR"
ls -la "$OUTDIR"/
