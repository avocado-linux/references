#include <cstdio>
#include <cstdlib>
#include <cstring>

#define CUDA_CHECK(call) do {                                          \
    cudaError_t _e = (call);                                           \
    if (_e != cudaSuccess) {                                           \
        fprintf(stderr, "CUDA error %s:%d: %s\n",                      \
                __FILE__, __LINE__, cudaGetErrorString(_e));           \
        exit(1);                                                       \
    }                                                                  \
} while (0)

__global__ void vectorAdd(const float *A, const float *B, float *C, int n) {
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i < n) C[i] = A[i] + B[i];
}

int main(int argc, char **argv) {
    int N     = (argc > 1) ? atoi(argv[1]) : (1 << 24);   // 16M elems
    int iters = (argc > 2) ? atoi(argv[2]) : 1000;        // ~1000 launches
    size_t bytes = (size_t)N * sizeof(float);

    int dev = 0;
    cudaDeviceProp prop{};
    CUDA_CHECK(cudaGetDeviceProperties(&prop, dev));
    printf("Device: %s (sm_%d%d, %d SMs, %.1f GB)\n",
           prop.name, prop.major, prop.minor,
           prop.multiProcessorCount,
           prop.totalGlobalMem / (1024.0 * 1024.0 * 1024.0));
    printf("N=%d iters=%d (per-iter: %.1f MB read + %.1f MB write)\n",
           N, iters, bytes / (1024.0 * 1024.0), bytes / (2 * 1024.0 * 1024.0));

    float *hA = (float*)malloc(bytes);
    float *hB = (float*)malloc(bytes);
    float *hC = (float*)malloc(bytes);
    for (int i = 0; i < N; i++) { hA[i] = (float)i; hB[i] = (float)(N - i); }

    float *dA, *dB, *dC;
    CUDA_CHECK(cudaMalloc(&dA, bytes));
    CUDA_CHECK(cudaMalloc(&dB, bytes));
    CUDA_CHECK(cudaMalloc(&dC, bytes));
    CUDA_CHECK(cudaMemcpy(dA, hA, bytes, cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(dB, hB, bytes, cudaMemcpyHostToDevice));

    int threads = 256;
    int blocks  = (N + threads - 1) / threads;

    cudaEvent_t start, stop;
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));

    // Warmup launch (excluded from timing).
    vectorAdd<<<blocks, threads>>>(dA, dB, dC, N);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    CUDA_CHECK(cudaEventRecord(start));
    for (int it = 0; it < iters; it++) {
        vectorAdd<<<blocks, threads>>>(dA, dB, dC, N);
    }
    CUDA_CHECK(cudaEventRecord(stop));
    CUDA_CHECK(cudaEventSynchronize(stop));

    float ms = 0;
    CUDA_CHECK(cudaEventElapsedTime(&ms, start, stop));
    CUDA_CHECK(cudaMemcpy(hC, dC, bytes, cudaMemcpyDeviceToHost));

    double gflops  = (double)N * iters / (ms * 1e6);
    double gbps_rw = (double)N * iters * sizeof(float) * 3 / (ms * 1e6); // 2 reads + 1 write

    printf("\nElapsed: %.2f ms  (%.0f launches/s)\n", ms, iters * 1000.0 / ms);
    printf("Throughput: %.2f GFLOPS, %.2f GB/s effective bandwidth\n", gflops, gbps_rw);
    printf("Sanity: hC[0]=%.1f, hC[N-1]=%.1f, expect %.1f for both\n",
           hC[0], hC[N - 1], (float)N);

    int ok = (hC[0] == (float)N) && (hC[N - 1] == (float)N);
    printf("Result: %s\n", ok ? "PASS" : "FAIL");

    cudaFree(dA); cudaFree(dB); cudaFree(dC);
    free(hA); free(hB); free(hC);
    return ok ? 0 : 1;
}
