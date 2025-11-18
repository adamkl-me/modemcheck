# Third-Party Licenses

This document lists the open-source libraries and dependencies used in Modem-Check, along with their respective licenses and copyright notices.

---

## Go Dependencies

### speedtest-go

**Package:** `github.com/showwin/speedtest-go v1.7.10`

**Purpose:** Provides native Go implementation for internet speed testing using Ookla speedtest.net servers. Used for measuring download/upload speeds, latency, and jitter without requiring external iperf3 installation.

**License:** MIT License

**Copyright:** Copyright (c) 2015 ITO Shogo

**License Text:**

```
The MIT License (MIT)

Copyright (c) 2015 ITO Shogo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/showwin/speedtest-go

---

### go-ping

**Package:** `github.com/go-ping/ping v1.2.0`

**Purpose:** Provides ICMP ping functionality in native Go for network latency testing. Used for measuring round-trip time, packet loss, and jitter to Google and Cloudflare servers.

**License:** MIT License

**Copyright:** Copyright (c) 2016 Cameron Sparr and contributors

**License Text:**

```
The MIT License (MIT)

Copyright (c) 2016 Cameron Sparr and contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/go-ping/ping

---

### google/uuid

**Package:** `github.com/google/uuid v1.2.0`

**Purpose:** Generates RFC 4122 compliant UUIDs. Used as a dependency by the ping library.

**License:** BSD-3-Clause License

**Copyright:** Copyright (c) 2009,2014 Google Inc. All rights reserved.

**License Text:**

```
Copyright (c) 2009,2014 Google Inc. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * Neither the name of Google Inc. nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

**Project URL:** https://github.com/google/uuid

---

### go-minisign

**Package:** `github.com/jedisct1/go-minisign`

**Purpose:** Pure Go implementation of Minisign signature verification. Used to cryptographically verify the authenticity and integrity of auto-update binaries, preventing supply chain attacks and ensuring only authorized updates are installed.

**License:** BSD-2-Clause License

**Copyright:** Copyright (c) 2018-2024 Frank Denis

**License Text:**

```
Copyright (c) 2018-2024, Frank Denis
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

**Project URL:** https://github.com/jedisct1/go-minisign

---

### golang.org/x Packages

**Packages:**
- `golang.org/x/net`
- `golang.org/x/sync`
- `golang.org/x/sys`
- `golang.org/x/crypto`

**Purpose:** Official Go supplementary libraries for networking, synchronization, system calls, and cryptography.

**License:** BSD-3-Clause License

**Copyright:** Copyright (c) 2009 The Go Authors. All rights reserved.

**License Text:**

```
Copyright (c) 2009 The Go Authors. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * Neither the name of Google Inc. nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

**Project URL:** https://golang.org/x

---

## External Tools

### Minisign (Build-time dependency)

**Tool:** Minisign command-line utility

**Purpose:** Signs release binaries during the build process. Required by developers building releases but not by end users. End users only need the verification capability (provided by go-minisign library embedded in the client).

**License:** ISC License

**Copyright:** Copyright (c) 2015-2024 Frank Denis

**License Text:**

```
ISC License

Copyright (c) 2015-2024 Frank Denis

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

**Project URL:** https://jedisct1.github.io/minisign/

**About the Author:** Frank Denis ([@jedisct1](https://github.com/jedisct1)) is a prominent security researcher and the creator of libsodium, DNSCrypt, and other widely-used security tools. Minisign is designed to be a simpler, more auditable alternative to GPG for software signing.

---

## Attribution Requirements

This project complies with all third-party license requirements:

1. **MIT Licensed Dependencies** (speedtest-go, go-ping, redis-py, argon2-cffi, FastAPI, Gunicorn, SQLAlchemy, Pydantic, Chart.js, chartjs-adapter-date-fns, zxcvbn):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided

2. **BSD-2-Clause Licensed Dependencies** (go-minisign):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided

3. **BSD-3-Clause Licensed Dependencies** (google/uuid, golang.org/x, Uvicorn):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided

4. **ISC Licensed Tools** (Minisign):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided
   - ℹ️ Build-time only (not distributed with binaries)

---

## Updating This Document

When adding new dependencies to `go.mod`, please update this document with:
- Package name and version
- Purpose and usage in the project
- License type
- Copyright holder
- Full license text
- Project URL

To check dependency licenses:
```bash
cd modemcheck-client
go list -m -json all | grep -A5 "Path"
```

Or visit the repository directly on GitHub to view the LICENSE file.

---

## Python Server Dependencies

### redis-py

**Package:** `redis 5.0.0` (Python Redis client)

**Purpose:** Provides Python client library for Redis, used for secure session management with atomic operations and automatic expiration in the cloud server component.

**License:** MIT License

**Copyright:** Copyright (c) 2012-2023 Redis Contributors

**License Text:**

```
MIT License

Copyright (c) 2012-2023 Redis Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/redis/redis-py

---

### argon2-cffi

**Package:** `argon2-cffi 23.1.0`

**Purpose:** Provides secure Argon2 password hashing algorithm (Argon2id variant). Used for protecting user passwords with memory-hard, GPU-resistant hashing in the cloud server authentication system.

**License:** MIT License

**Copyright:** Copyright (c) 2015 Hynek Schlawack and the argon2-cffi contributors

**License Text:**

```
The MIT License (MIT)

Copyright (c) 2015 Hynek Schlawack and the argon2-cffi contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/hynek/argon2-cffi

---

## Python FastAPI Backend Dependencies

### FastAPI

**Package:** `fastapi 0.115.5`

**Purpose:** Modern async web framework for building APIs. Used as the foundation for the v2 cloud server, providing automatic OpenAPI documentation, type safety with Pydantic, dependency injection, and high-performance async request handling.

**License:** MIT License

**Copyright:** Copyright (c) 2018 Sebastián Ramírez

**License Text:**

```
MIT License

Copyright (c) 2018 Sebastián Ramírez

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/fastapi/fastapi

---

### Uvicorn

**Package:** `uvicorn 0.32.1`

**Purpose:** Lightning-fast ASGI server implementation for Python. Runs FastAPI applications with async/await support, WebSocket handling, and automatic reload during development. Production deployment uses Gunicorn with Uvicorn workers.

**License:** BSD-3-Clause License

**Copyright:** Copyright (c) 2017-present, Encode OSS Ltd.

**License Text:**

```
BSD 3-Clause License

Copyright (c) 2017-present, Encode OSS Ltd.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

**Project URL:** https://github.com/encode/uvicorn

---

### Gunicorn

**Package:** `gunicorn 23.0.0`

**Purpose:** Pre-fork Python WSGI/ASGI HTTP server for production deployments. Manages multiple Uvicorn worker processes, provides process monitoring, graceful restarts, and load balancing for high-concurrency cloud server operations.

**License:** MIT License

**Copyright:**
- Copyright (c) 2009-2024 Benoît Chesneau <benoitc@gunicorn.org>
- Copyright (c) 2009-2015 Paul J. Davis <paul.joseph.davis@gmail.com>

**License Text:**

```
MIT License

Copyright (c) 2009-2024 Benoît Chesneau <benoitc@gunicorn.org>
Copyright (c) 2009-2015 Paul J. Davis <paul.joseph.davis@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/benoitc/gunicorn

---

### SQLAlchemy

**Package:** `sqlalchemy 2.0.36`

**Purpose:** Python SQL toolkit and Object-Relational Mapping (ORM) library. Provides async database operations, connection pooling, and JSONB support for PostgreSQL. Maps database tables to Python classes for type-safe modem data storage and queries.

**License:** MIT License

**Copyright:** Copyright (c) 2005-2025 SQLAlchemy authors and contributors

**License Text:**

```
MIT License

Copyright (c) 2005-2025 SQLAlchemy authors and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/sqlalchemy/sqlalchemy

---

### Pydantic

**Package:** `pydantic 2.10.3`

**Purpose:** Data validation and settings management using Python type annotations. Validates API requests/responses, provides automatic JSON serialization, and ensures type safety throughout the FastAPI application with runtime validation.

**License:** MIT License

**Copyright:** Copyright (c) 2017-present Pydantic Services Inc. and individual contributors

**License Text:**

```
MIT License

Copyright (c) 2017-present Pydantic Services Inc. and individual contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/pydantic/pydantic

---

### SlowAPI

**Package:** `slowapi 0.1.9`

**Purpose:** Rate limiting library for FastAPI with Redis backend support. Provides distributed rate limiting across multiple workers, protecting authentication endpoints (30 req/min), upload endpoints (60 req/min), and API endpoints (300 req/sec) from abuse and DoS attacks.

**License:** MIT License

**Copyright:** Copyright (c) 2020 Laurent Savaete

**License Text:**

```
MIT License

Copyright (c) 2020 Laurent Savaete

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/laurentS/slowapi

---

## JavaScript Frontend Dependencies

### Chart.js

**Package:** `Chart.js 4.4.0`

**Purpose:** Flexible JavaScript charting library for data visualization. Renders interactive time-series graphs in the cloud data viewer, displaying historical trends for signal levels, speeds, latency, and other modem metrics with zoom, pan, and tooltip interactions.

**License:** MIT License

**Copyright:** Copyright (c) 2014-2024 Chart.js Contributors

**License Text:**

```
MIT License

Copyright (c) 2014-2024 Chart.js Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/chartjs/Chart.js

---

### chartjs-adapter-date-fns

**Package:** `chartjs-adapter-date-fns 3.0.0`

**Purpose:** Date adapter for Chart.js time-scale axes using date-fns library. Enables accurate time-based x-axis rendering for modem diagnostic trends, handling timezone conversions and date formatting for historical data visualization.

**License:** MIT License

**Copyright:** Copyright (c) 2019 Chart.js Contributors

**License Text:**

```
MIT License

Copyright (c) 2019 Chart.js Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/chartjs/chartjs-adapter-date-fns

---

### zxcvbn

**Package:** `zxcvbn 4.4.2` (JavaScript password strength estimator)

**Purpose:** Provides realistic password strength estimation in the admin dashboard. Used for real-time feedback on password security during user account creation and password changes.

**License:** MIT License

**Copyright:** Copyright (c) 2012-2016 Dan Wheeler and Dropbox, Inc.

**License Text:**

```
The MIT License (MIT)

Copyright (c) 2012-2016 Dan Wheeler and Dropbox, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Project URL:** https://github.com/dropbox/zxcvbn

---

## Acknowledgments

Special thanks to:

**Go Client Contributors:**
- **ITO Shogo** for creating speedtest-go, enabling native Go speed testing
- **Cameron Sparr and contributors** for go-ping, providing ICMP ping in pure Go
- **Frank Denis** for Minisign and go-minisign, providing simple and secure cryptographic signing
- **Google** for the UUID library
- **The Go Authors** for the official supplementary packages including crypto libraries
- **Ookla** for speedtest.net infrastructure used by speedtest-go

**Python Backend Contributors:**
- **Sebastián Ramírez** for FastAPI, providing modern async web framework capabilities
- **Encode OSS Ltd** for Uvicorn, enabling high-performance ASGI server operations
- **Benoît Chesneau and Paul J. Davis** for Gunicorn, providing production-grade process management
- **SQLAlchemy authors and contributors** for the powerful async ORM and database toolkit
- **Pydantic Services Inc. and contributors** for data validation and type safety
- **Laurent Savaete** for SlowAPI, enabling distributed rate limiting with Redis backend
- **Redis Contributors** for redis-py, enabling secure session management and caching
- **Hynek Schlawack and argon2-cffi contributors** for providing secure Argon2 password hashing

**JavaScript Frontend Contributors:**
- **Chart.js Contributors** for the flexible charting library enabling interactive data visualization
- **Chart.js Contributors** for chartjs-adapter-date-fns, enabling accurate time-series rendering
- **Dan Wheeler and Dropbox** for zxcvbn, enabling realistic password strength estimation

These libraries and tools make it possible for Modem-Check to run as a single, standalone, securely-updatable binary with no external runtime dependencies, and provide enterprise-grade security and scalability for the FastAPI-based cloud server component.

---

*Last Updated: 2025-11-17*
