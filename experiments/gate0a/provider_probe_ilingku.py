#!/usr/bin/env python3
"""Run the Gate 0A provider probe against the iLingku public Douyin endpoint."""

import provider_probe as probe

probe.SOURCE_PROVIDER = "ILINGKU_PUBLIC_API"
probe.AUTHORIZATION_BASIS = "PUBLIC_DOCS_ONLY_UNVERIFIED"
probe.ENDPOINT = "https://api.ilingku.com/int/v1/douyinlive"

raise SystemExit(probe.main())
