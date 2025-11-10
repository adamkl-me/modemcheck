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

### golang.org/x Packages

**Packages:**
- `golang.org/x/net`
- `golang.org/x/sync`
- `golang.org/x/sys`

**Purpose:** Official Go supplementary libraries for networking, synchronization, and system calls.

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

## Attribution Requirements

This project complies with all third-party license requirements:

1. **MIT Licensed Dependencies** (speedtest-go, go-ping):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided

2. **BSD-3-Clause Licensed Dependencies** (google/uuid, golang.org/x):
   - ✅ Copyright notices preserved
   - ✅ License text included
   - ✅ Attribution provided

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

## Acknowledgments

Special thanks to:
- **ITO Shogo** for creating speedtest-go, enabling native Go speed testing
- **Cameron Sparr and contributors** for go-ping, providing ICMP ping in pure Go
- **Google** for the UUID library
- **The Go Authors** for the official supplementary packages
- **Ookla** for speedtest.net infrastructure used by speedtest-go

These libraries make it possible for Modem-Check to run as a single, standalone binary with no external dependencies.

---

*Last Updated: 2025-11-10*
