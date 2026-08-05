module modemcheck-client

go 1.25

require (
	github.com/aeden/traceroute v0.0.0-20210211061815-03f5f7cb7908
	github.com/denisbrodbeck/machineid v1.0.1
	github.com/go-ping/ping v1.2.0
	github.com/gofrs/flock v0.13.0
	github.com/jedisct1/go-minisign v0.0.0-20241212093149-d2f9f49435c7
	github.com/showwin/speedtest-go v1.7.10
	golang.org/x/crypto v0.48.0
)

require (
	github.com/google/uuid v1.6.0 // indirect
	golang.org/x/net v0.50.0 // indirect
	golang.org/x/sync v0.19.0 // indirect
	golang.org/x/sys v0.41.0 // indirect
)

replace github.com/pixelbender/go-traceroute => github.com/aeden/traceroute v0.0.0-20210211061815-03f5f7cb7908
