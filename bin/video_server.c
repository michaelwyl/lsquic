/* Copyright (c) 2017 - 2022 LiteSpeed Technologies Inc.  See LICENSE. */
/*
 * video_server.c -- A standalone QUIC HTTP/3 server for serving video files
 *
 * Usage: ./video_server -s ip:port -r ./video -A 2 -c domain,cert.pem,key.pem
 */

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/queue.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <inttypes.h>

#ifndef WIN32
#include <unistd.h>
#include <fcntl.h>
#else
#include "vc_compat.h"
#include "getopt.h"
#endif

#include <event2/event.h>

#include "lsquic.h"
#include "../src/liblsquic/lsquic_hash.h"
#include "lsxpack_header.h"
#include "test_config.h"
#include "test_common.h"
#include "test_cert.h"
#include "prog.h"

#include "../src/liblsquic/lsquic_logger.h"

/* Server context - holds global server state */
struct server_ctx {
    struct lsquic_conn_ctx  *conn_h;
    lsquic_engine_t         *engine;
    const char              *document_root;
    struct sport_head        sports;
    struct prog             *prog;
    unsigned                 n_current_conns;
};

/* Connection context - per-connection state */
struct lsquic_conn_ctx {
    lsquic_conn_t       *conn;
    struct server_ctx   *server_ctx;
};

/* Stream context - per-stream state */
struct lsquic_stream_ctx {
    lsquic_stream_t     *stream;
    struct server_ctx   *server_ctx;
    char                *req_buf;
    size_t               req_sz;
    char                *req_filename;
    char                *req_path;
    struct lsquic_reader reader;
    int                  headers_sent;
};


/*
 * Callback: New connection established
 */
static lsquic_conn_ctx_t *
video_server_on_new_conn (void *stream_if_ctx, lsquic_conn_t *conn)
{
    struct server_ctx *server_ctx = stream_if_ctx;
    const char *sni;

    sni = lsquic_conn_get_sni(conn);
    LSQ_DEBUG("New connection, SNI: %s", sni ? sni : "<not set>");

    lsquic_conn_ctx_t *conn_h = malloc(sizeof(*conn_h));
    if (!conn_h)
        return NULL;

    conn_h->conn = conn;
    conn_h->server_ctx = server_ctx;
    server_ctx->conn_h = conn_h;
    ++server_ctx->n_current_conns;

    return conn_h;
}


/*
 * Callback: Connection closed
 */
static void
video_server_on_conn_closed (lsquic_conn_t *conn)
{
    lsquic_conn_ctx_t *conn_h = lsquic_conn_get_ctx(conn);

    LSQ_INFO("Connection closed");
    --conn_h->server_ctx->n_current_conns;
    lsquic_conn_set_ctx(conn, NULL);
    free(conn_h);
}


/*
 * Callback: New stream created
 */
static lsquic_stream_ctx_t *
video_server_on_new_stream (void *stream_if_ctx, lsquic_stream_t *stream)
{
    lsquic_stream_ctx_t *st_h = calloc(1, sizeof(*st_h));
    if (!st_h)
        return NULL;

    st_h->stream = stream;
    st_h->server_ctx = stream_if_ctx;
    lsquic_stream_wantread(stream, 1);

    return st_h;
}


/*
 * Helper: Check if filename ends with extension
 */
static int
ends_with (const char *filename, const char *ext)
{
    const char *where = strstr(filename, ext);
    return where && strlen(where) == strlen(ext);
}


/*
 * Helper: Select content type based on file extension
 */
static const char *
select_content_type (const char *filename)
{
    /* Video formats */
    if (ends_with(filename, ".mp4"))
        return "video/mp4";
    if (ends_with(filename, ".webm"))
        return "video/webm";
    if (ends_with(filename, ".m4s"))
        return "video/iso.segment";
    if (ends_with(filename, ".m4v"))
        return "video/mp4";
    if (ends_with(filename, ".m4a"))
        return "audio/mp4";

    /* DASH/HLS manifest formats */
    if (ends_with(filename, ".mpd"))
        return "application/dash+xml";
    if (ends_with(filename, ".m3u8"))
        return "application/vnd.apple.mpegurl";

    /* Web formats */
    if (ends_with(filename, ".html"))
        return "text/html";
    if (ends_with(filename, ".js"))
        return "application/javascript";
    if (ends_with(filename, ".css"))
        return "text/css";
    if (ends_with(filename, ".json"))
        return "application/json";

    /* Image formats */
    if (ends_with(filename, ".png"))
        return "image/png";
    if (ends_with(filename, ".jpg") || ends_with(filename, ".jpeg"))
        return "image/jpeg";
    if (ends_with(filename, ".gif"))
        return "image/gif";

    /* Text */
    if (ends_with(filename, ".txt"))
        return "text/plain";

    /* Default */
    return "application/octet-stream";
}


/*
 * Helper: Send HTTP/3 response headers
 */
static int
send_headers (lsquic_stream_t *stream, lsquic_stream_ctx_t *st_h,
              const char *status, const char *content_type)
{
    struct header_buf hbuf;
    struct lsxpack_header headers_arr[2];

    hbuf.off = 0;
    header_set_ptr(&headers_arr[0], &hbuf, ":status", 7, status, strlen(status));
    header_set_ptr(&headers_arr[1], &hbuf, "content-type", 12,
                   content_type, strlen(content_type));

    lsquic_http_headers_t headers = {
        .count = 2,
        .headers = headers_arr,
    };

    if (0 != lsquic_stream_send_headers(stream, &headers, 0))
    {
        LSQ_ERROR("Cannot send headers: %s", strerror(errno));
        return -1;
    }

    st_h->headers_sent = 1;
    return 0;
}


/*
 * Helper: Parse HTTP request path from buffer
 * Expects format like: "GET /path HTTP/1.1\r\n..."
 */
static char *
parse_request_path (const char *req_buf, size_t req_sz)
{
    const char *start, *end;
    char *path;
    size_t path_len;

    /* Find start of path (after "GET ") */
    if (req_sz < 5 || strncmp(req_buf, "GET ", 4) != 0)
        return NULL;

    start = req_buf + 4;

    /* Find end of path (before " HTTP") */
    end = strstr(start, " HTTP");
    if (!end)
        return NULL;

    path_len = end - start;
    path = malloc(path_len + 1);
    if (!path)
        return NULL;

    memcpy(path, start, path_len);
    path[path_len] = '\0';

    return path;
}


/*
 * Callback: Stream has data to read
 */
static void
video_server_on_read (lsquic_stream_t *stream, lsquic_stream_ctx_t *st_h)
{
    unsigned char buf[0x400];
    ssize_t nread;
    char *path;
    char *filename;

    /* Read request data */
    nread = lsquic_stream_read(stream, buf, sizeof(buf) - 1);

    if (nread > 0)
    {
        /* Accumulate request data */
        char *new_buf = realloc(st_h->req_buf, st_h->req_sz + nread + 1);
        if (!new_buf)
        {
            LSQ_ERROR("Memory allocation failed");
            lsquic_stream_close(stream);
            return;
        }
        st_h->req_buf = new_buf;
        memcpy(st_h->req_buf + st_h->req_sz, buf, nread);
        st_h->req_sz += nread;
        st_h->req_buf[st_h->req_sz] = '\0';
        return;
    }

    if (nread < 0)
    {
        LSQ_ERROR("Error reading: %s", strerror(errno));
        lsquic_stream_close(stream);
        return;
    }

    /* nread == 0: End of request */
    LSQ_INFO("Got request: `%.*s'", (int)(st_h->req_sz > 100 ? 100 : st_h->req_sz),
             st_h->req_buf ? st_h->req_buf : "");

    /* Parse request path */
    path = parse_request_path(st_h->req_buf, st_h->req_sz);
    if (!path)
    {
        LSQ_WARN("Failed to parse request path");
        send_headers(stream, st_h, "400", "text/plain");
        lsquic_stream_shutdown(stream, 1);
        return;
    }

    /* Construct full filename */
    filename = malloc(strlen(st_h->server_ctx->document_root) + strlen(path) + 2);
    if (!filename)
    {
        free(path);
        LSQ_ERROR("Memory allocation failed");
        lsquic_stream_close(stream);
        return;
    }

    strcpy(filename, st_h->server_ctx->document_root);
    if (path[0] != '/')
        strcat(filename, "/");
    strcat(filename, path);

    LSQ_INFO("Serving file: %s", filename);

    st_h->req_filename = filename;
    st_h->req_path = path;

    /* Set up file reader */
    st_h->reader.lsqr_read = test_reader_read;
    st_h->reader.lsqr_size = test_reader_size;
    st_h->reader.lsqr_ctx = create_lsquic_reader_ctx(filename);

    if (!st_h->reader.lsqr_ctx)
    {
        LSQ_WARN("File not found: %s", filename);
        send_headers(stream, st_h, "404", "text/plain");
        lsquic_stream_shutdown(stream, 1);
        return;
    }

    /* Ready to write response */
    lsquic_stream_shutdown(stream, 0);  /* Done reading */
    lsquic_stream_wantwrite(stream, 1);
}


/*
 * Callback: Stream is ready for writing
 */
static void
video_server_on_write (lsquic_stream_t *stream, lsquic_stream_ctx_t *st_h)
{
    ssize_t nw;

    /* Send headers first */
    if (!st_h->headers_sent)
    {
        const char *content_type = select_content_type(st_h->req_filename);
        if (0 != send_headers(stream, st_h, "200", content_type))
        {
            lsquic_stream_close(stream);
            return;
        }
    }

    /* Write file content */
    if (st_h->reader.lsqr_ctx && test_reader_size(st_h->reader.lsqr_ctx) > 0)
    {
        nw = lsquic_stream_writef(stream, &st_h->reader);
        if (nw < 0)
        {
            LSQ_ERROR("Write error: %s", strerror(errno));
            lsquic_stream_close(stream);
            return;
        }

        /* More data to write? */
        if (test_reader_size(st_h->reader.lsqr_ctx) > 0)
        {
            lsquic_stream_wantwrite(stream, 1);
            return;
        }
    }

    /* Done writing */
    lsquic_stream_shutdown(stream, 1);
}


/*
 * Callback: Stream closed
 */
static void
video_server_on_close (lsquic_stream_t *stream, lsquic_stream_ctx_t *st_h)
{
    LSQ_DEBUG("Stream closed");

    free(st_h->req_buf);
    free(st_h->req_filename);
    free(st_h->req_path);

    if (st_h->reader.lsqr_ctx)
        destroy_lsquic_reader_ctx(st_h->reader.lsqr_ctx);

    free(st_h);
}


/* Stream callback interface */
static const struct lsquic_stream_if video_server_if = {
    .on_new_conn    = video_server_on_new_conn,
    .on_conn_closed = video_server_on_conn_closed,
    .on_new_stream  = video_server_on_new_stream,
    .on_read        = video_server_on_read,
    .on_write       = video_server_on_write,
    .on_close       = video_server_on_close,
};


static void
usage (const char *prog_name)
{
    printf(
"Usage: %s [options]\n"
"\n"
"Options:\n"
"   -r DIR      Document root directory (required)\n"
"   -s IP:PORT  Server address and port (e.g., 0.0.0.0:443)\n"
"   -A ALGO     Congestion control algorithm:\n"
"                 1 = Cubic\n"
"                 2 = BBRv1\n"
"                 3 = Adaptive (default)\n"
"   -c CERT     Certificate spec: domain,cert.pem,key.pem\n"
"   -L LEVEL    Log level (debug, info, notice, warn, error)\n"
"   -h          Print this help message\n"
"\n"
"Example:\n"
"   %s -s 0.0.0.0:443 -r ./video -A 2 -c example.com,cert.pem,key.pem\n"
"\n",
        prog_name, prog_name);
}


int
main (int argc, char **argv)
{
    int opt, s;
    struct stat st;
    struct server_ctx server_ctx;
    struct prog prog;
    const char *const *alpn;

    memset(&server_ctx, 0, sizeof(server_ctx));
    TAILQ_INIT(&server_ctx.sports);
    server_ctx.prog = &prog;

    /* Initialize program with server + HTTP flags */
    prog_init(&prog, LSENG_SERVER | LSENG_HTTP, &server_ctx.sports,
              &video_server_if, &server_ctx);

    /* Hardcode BBR congestion control (2 = BBRv1) */
    prog.prog_settings.es_cc_algo = 2;

    /* Parse command line options */
    while (-1 != (opt = getopt(argc, argv, PROG_OPTS "r:h")))
    {
        switch (opt) {
        case 'r':
            /* Document root */
            if (-1 == stat(optarg, &st))
            {
                perror("stat");
                exit(2);
            }
#ifndef WIN32
            if (!S_ISDIR(st.st_mode))
            {
                fprintf(stderr, "'%s' is not a directory\n", optarg);
                exit(2);
            }
#endif
            server_ctx.document_root = optarg;
            break;

        case 'h':
            usage(argv[0]);
            prog_print_common_options(&prog, stdout);
            exit(0);

        default:
            /* Let prog handle common options like -s, -A, -c, -L */
            if (0 != prog_set_opt(&prog, opt, optarg))
                exit(1);
        }
    }

    /* Validate required options */
    if (!server_ctx.document_root)
    {
        fprintf(stderr, "Error: Document root (-r) is required\n");
        usage(argv[0]);
        exit(1);
    }

    /* Set up ALPN protocols for HTTP/3 */
    alpn = lsquic_get_h3_alpns(prog.prog_settings.es_versions);
    while (*alpn)
    {
        if (0 == add_alpn(*alpn))
            ++alpn;
        else
        {
            LSQ_ERROR("Cannot add ALPN %s", *alpn);
            exit(EXIT_FAILURE);
        }
    }

    /* Prepare the engine */
    if (0 != prog_prep(&prog))
    {
        LSQ_ERROR("Could not prepare server");
        exit(EXIT_FAILURE);
    }

    LSQ_NOTICE("Video server starting, document root: %s", server_ctx.document_root);

    /* Run event loop */
    s = prog_run(&prog);

    /* Cleanup */
    prog_cleanup(&prog);

    return s == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
