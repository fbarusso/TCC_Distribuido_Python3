from mpi4py import MPI
import time
import sys
import gc

import matplotlib.pylab as plt

from mpc_function import *
from polyapprox_function import *

# system parameters
comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

if len(sys.argv) == 1:
    if rank == 0:
        print("ERROR: please input the number of workers")
    exit()
else:
    N = int(sys.argv[1])

N_case = 2
K_ = [int(np.floor((N - 1) / float(3))), int(np.floor((N - 1) / float(3))) + 1 - int(np.floor((N - 3) / float(6))),
      int(1)]
T_ = [int(1), int(np.floor((N - 3) / float(6))), int(np.floor((N - 1) / float(3)))]

# learning parameters
max_iter = 50
np.random.seed(42)  # set the seed of the random number generator for consistency

p, q_bit_X, q_bit_y = 2 ^ 26 - 5, 2, 0

alpha_exp = 10
coeffs0_exp = 1
coeffs1_exp = 11
trunc_scale = alpha_exp + coeffs1_exp - q_bit_y
trunc_k, trunc_m = 24, trunc_scale

# for debugging
Load_images_ON = 0  # 0: using synthetic data, 1: Load GISETTE data
m_syn, d_syn = 200, 100

debugging_X_LCC = 0
debugging_w_LCC = 0
debugging_f_SS_T = 0
debugging_w_SS_T = 0
debugging_hist_w_SS_T = 1

if rank == 0:
    print("Hi from crypto-service provider", "rank", rank)

    if Load_images_ON == 1:

        t0_read = time.time()  # start timer

        print("00. Load Gisette")
        dir = "./"
        f = open(dir + "gisette_train.data")
        data = []
        for row in f.readlines():
            data.append((row.strip()).split(" "))
        f.close()

        f = open(dir + "gisette_train.labels")
        classes = []
        for row in f.readlines():
            classes.append((row.strip()).split(" "))
        f.close()

        X_train, y_train = np.array(data).astype(int), np.array(classes).astype(int)

        f = open(dir + "gisette_valid.data")
        data = []
        for row in f.readlines():
            data.append((row.strip()).split(" "))
        f.close()

        f = open(dir + "gisette_valid.labels")
        classes = []
        for row in f.readlines():
            classes.append((row.strip()).split(" "))
        f.close()

        X_test, y_test = np.array(data).astype(int), np.array(classes).astype(int)

        print("Dim: X_train, y_train = ", np.shape(X_train), np.shape(y_train))
        print("Dim: X_test, y_test = ", np.shape(X_test), np.shape(y_test))

        t_read = time.time() - t0_read
        print("Time spent for reading dataset (sec)", t_read)

        m, d = np.shape(X_train)
        X_train = X_train / np.max(X_train)
        X_test = X_test / np.max(X_test)

        y_test = (y_test + 1) / 2
        y_train = (y_train + 1) / 2

        X = X_train

        m, d = X.shape
        y = np.reshape(y_train, (m, 1))  # reshape row vector into a column vector
        y_test = np.reshape(y_test, (len(y_test), 1))

        # release the memory
        X_train = None
        y_train = None

        t_read = time.time() - t0_read  # time spent in reading dataset

        gc.collect()

    else:
        m_syn, d_syn = 200, 100

        t0_read = time.time()  # start timer
        X = np.random.randint(p, size=(m_syn, d_syn), dtype="int64")
        y = np.random.randint(2, size=(m_syn, 1), dtype="int64")
        m, d = X.shape
        t_read = time.time() - t0_read  # time spent in reading dataset

    print("Time spent for reading dataset (sec)", t_read)
    print("Train data shape: ", X.shape)
    print("Train labels shape: ", y.shape)

    time_out = []

    K = K_[N_case]  # number of submatrices
    T = T_[N_case]

    print(N_case + 1, "st case: (K,T)=", K, T)

    m = X.shape[0] - (X.shape[
                          0] % K)  # remove extra data points so that m is divisible by k, i.e., put data suitable for LCC format

    X = X[:m]  # extract the first m rows
    y = y[:m]  # extract the first m elements
    y = np.reshape(y, (m, 1))  # reshape row vector into a column vector

    t0_offline = time.time()

    print("01.Data conversion: real to finite field")
    t0_q = time.time()
    X_q = my_q(X, q_bit_X, p)  # X_q: matrix with size ( m by d )

    t_q = time.time() - t0_q  # time spent in reading dataset

    y_scale = ((2 ** q_bit_y) * y).astype("int64")

    print("02. Secret Shares generation in finite field")
    t0 = time.time()
    X_SS_T = BGW_encoding(X_q, N, T, p)
    t_gen_X_SS_T = time.time() - t0

    for j in list(range(1, N + 1)):
        data_X_T = np.reshape(X_SS_T[j - 1, :, :], d * m)  # send data in vector format

        comm.send(m, dest=j)  # send number of rows =  number of training samples
        comm.send(d, dest=j)  # send number of columns = number of features
        comm.Send(data_X_T, dest=j)  # sent data to worker j
    data_X_T, X_SS_T = None, None
    gc.collect()

    print("03. Random matrix and corresponding SS generation")
    r_mult1 = np.random.randint(p, size=(m, 1))
    r_mult1_SS_T = BGW_encoding(r_mult1, N, T, p)
    r_mult1_SS_2T = BGW_encoding(r_mult1, N, 2 * T, p)

    r_mult2 = np.random.randint(p, size=(d, 1))
    r_mult2_SS_T = BGW_encoding(r_mult2, N, T, p)
    r_mult2_SS_2T = BGW_encoding(r_mult2, N, 2 * T, p)

    r1 = np.random.randint(2 ** trunc_m, size=(d, 1))
    r2 = np.random.randint(2 ** (trunc_k - trunc_m), size=(d, 1))

    r1_BGW = BGW_encoding(r1, N, T, p)
    r2_BGW = BGW_encoding(r2, N, T, p)

    # initialize model parameters
    w = (1 / float(m)) * np.random.rand(d, 1)
    w_q_tmp = my_q(w, 0, p)
    w_SS_T = BGW_encoding(w_q_tmp, N, T, p)

    # random matrix for LCC encoding
    R_LCC = np.random.randint(p, size=(T, int(m / K), d))
    r_LCC = np.random.randint(p, size=(T, d, 1))

    # generation Secret shares of the random matrix
    R_LCC_SS_T = np.empty((N, T, int(m / K), d), dtype="int64")
    for t in list(range(T)):
        R_LCC_SS_T[:, t, :, :] = BGW_encoding(R_LCC[t, :, :], N, T, p)

    r_LCC_SS_T = np.empty((N, T, d, 1), dtype="int64")
    for t in list(range(T)):
        r_LCC_SS_T[:, t, :, :] = BGW_encoding(r_LCC[t, :, :], N, T, p)

    t0_CSP_send_SS = time.time()

    print("(m, d, K, T, int(m / K)) =", m, d, K, T, int(m / K))

    # Sending data to workers @ preprocessing
    for j in list(range(1, N + 1)):
        # print("Sending data to worker", j)

        data_y = np.reshape(y_scale, m)  # send data in vector format
        data_w_T = np.reshape(w_SS_T[j - 1, :, :], d)  # send data in vector format
        data_R1_T = np.reshape(r_mult1_SS_T[j - 1, :, :], m)  # send data in vector format
        data_R1_2T = np.reshape(r_mult1_SS_2T[j - 1, :, :], m)  # send data in vector format
        data_R2_T = np.reshape(r_mult2_SS_T[j - 1, :, :], d)  # send data in vector format
        data_R2_2T = np.reshape(r_mult2_SS_2T[j - 1, :, :], d)  # send data in vector format

        data_r1_T = np.reshape(r1_BGW[j - 1, :, :], d)  # send data in vector format
        data_r2_T = np.reshape(r2_BGW[j - 1, :, :], d)  # send data in vector format

        data_R_LCC_T = np.reshape(R_LCC_SS_T[j - 1, :, :, :], T * (int(m / K)) * d)
        data_r_LCC_T = np.reshape(r_LCC_SS_T[j - 1, :, :, :], T * d)

        comm.Send(data_y, dest=j)  # sent data to worker j
        comm.Send(data_w_T, dest=j)  # sent data to worker j
        comm.Send(data_R1_T, dest=j)  # sent data to worker j
        comm.Send(data_R1_2T, dest=j)  # sent data to worker j
        comm.Send(data_R2_T, dest=j)  # sent data to worker j
        comm.Send(data_R2_2T, dest=j)  # sent data to worker j

        comm.Send(data_r1_T, dest=j)  # sent data to worker j
        comm.Send(data_r2_T, dest=j)  # sent data to worker j

        comm.Send(data_R_LCC_T, dest=j)
        comm.Send(data_r_LCC_T, dest=j)
    comm.Barrier()

    t_CSP_send_SS = time.time() - t0_CSP_send_SS
    t_offline = time.time() - t0_offline

    print("[crypto - service provider] sending X_SS_T & random SS is done")
    print("[crypto - service provider] Offline Time =", t_offline, "sending SS in offline phase =", t_CSP_send_SS)

    print("start garbage collection")

    data_y, y_scale, data_w_T, w_SS_T = None, None, None, None
    data_R1_T, data_R1_2T, data_R2_T = None, None, None
    data_R2_2T, data_r1_T, data_r2_T = None, None, None
    data_R_LCC_T, data_r_LCC_T, X_SS_T, data_X_T = None, None, None, None
    R_LCC_SS_T, r_LCC_SS_T, r1_BGW, r2_BGW = None, None, None, None

    gc.collect()
    print("garbage collection is done")

    # for debugging
    if debugging_X_LCC == 1:
        print("debugging from crypto-service provider")
        # debugging for X_LCC encoding & decoding @ workers
        X_LCC = np.empty((N, (int(m / K)) * d), dtype="int64")
        for j in list(range(1, N + 1)):
            comm.Recv(X_LCC[j - 1, :], source=j)

        # for comparison
        X_LCC_tmp = LCC_encoding_w_Random(X_q, R_LCC, N, K, T, p)
        print(X_LCC_tmp[:, 0, 0:3])
        print(X_LCC[:, 0:3])

        worker_idx = random.sample(list(range(N)), T + K)
        # print(worker_idx)
        X_sub = LCC_decoding(X_LCC[worker_idx, :], T + K, N, K, T, worker_idx, p)

        print(X_q[0, 350:353])
        print(X_sub[0, 350:353])
        print(X_sub.shape)

    if debugging_w_LCC == 1:
        w_LCC = np.empty((N, d), dtype="int64")
        for j in list(range(1, N + 1)):
            comm.Recv(w_LCC[j - 1, :], source=j)
        w_dec = LCC_decoding(w_LCC[worker_idx, :], T + 1, N, K, T, worker_idx, p)
        print(w_q_tmp.T[0, 0:3])
        print(w_dec[0, 0:3])

    if debugging_f_SS_T:
        f_SS_T = np.empty((N, d), dtype="int64")
        for j in list(range(1, N + 1)):
            comm.Recv(f_SS_T[j - 1, :], source=j)

        worker_idx = random.sample(list(range(N)), T + 1)  # XXX
        f_dec = BGW_decoding(f_SS_T[worker_idx, :], worker_idx, p)
        print(f_dec[0, 0:3])

    if debugging_w_SS_T:
        iter = 0
        while iter < max_iter:
            iter = iter + 1
            w_SS_T_ = np.empty((N, d), dtype="int64")
            for j in list(range(1, N + 1)):
                comm.Recv(w_SS_T_[j - 1, :], source=j)

            worker_idx = random.sample(list(range(N)), T + 1)  # XXX
            w_dec = BGW_decoding(w_SS_T_[worker_idx, :], worker_idx, p)
            # print(w_dec[0,300:350])
            w_tmp = my_q_inv(w_dec, 0, p)
            w_tmp = (2 ** (-q_bit_y)) * np.reshape(w_tmp, (d, 1))

            f = sigmoid(X.dot(np.reshape(w_tmp, (d, 1))))
            error = -(1 / float(len(y))) * (np.dot(y.T, np.log(f)) + np.dot(1 - y.T, np.log(1 - f)))
            print("from w_SS_T, iter=", iter)
            # print(worker_idx)
            print("error=", error)

            plt.title("field size = p =" + str(p))
            plt.plot(w_tmp, "r")
            # plt.plot(c0_my,"b")
            plt.legend(["w_dec"])
            plt.show()

    if debugging_hist_w_SS_T == 1:
        print("from hist_w_SS_T")
        # print(worker_idx)
        dec_input = np.empty((N, max_iter + 1, d), dtype="int64")
        for j in list(range(1, N + 1)):
            data = np.empty((max_iter + 1) * d, dtype="int64")
            comm.Recv(data, source=j)
            dec_input[j - 1, :, :] = np.reshape(data, (max_iter + 1, d))

        worker_idx = list(range(N))  # XXX
        for i in list(range(max_iter + 1)):
            w_dec = BGW_decoding(dec_input[worker_idx, i, :], worker_idx, p)
            w_tmp = my_q_inv(w_dec, 0, p)
            w_tmp = (2 ** (-q_bit_y)) * np.reshape(w_tmp, (d, 1))

            f = sigmoid(X.dot(w_tmp))
            error = -(1 / float(len(y))) * (np.dot(y.T, np.log(f)) + np.dot(1 - y.T, np.log(1 - f)))

            print(i, error)

    N_time_set = 11
    time_set_workers = np.empty((N, N_time_set), dtype="float")
    for j in list(range(1, N + 1)):
        comm.Recv(time_set_workers[j - 1, :], source=j)
    # print(time_set)

    total_time = time.time() - t0_offline
    print("[crypto - service provider] Total training time =", total_time)

    time_set = {"K": K,
                "T": T,
                "total_time": total_time,
                "t_CSP_send_SS": t_CSP_send_SS,
                "t_offline": t_offline,
                "t_gen_X_SS_T": t_gen_X_SS_T,
                "time_set_workers": time_set_workers}

    T_workers = np.sum(time_set_workers, axis=0) / N
    # t_LCC_encoding_X(0), t_XTX(1), t_XTy(2), t_LCC_encoding_w(3), t_f_eval(4), t_gen_f_SS(5)
    # t_gen_grad_SS(6), t_comm_f_eval_SS(7), t_trunc(8). t_preprocessing(9), t_mainloop(10))

    print("gen LCC=", T_workers[0])
    print("each iteration")
    print("gen w_LCC=", T_workers[3])
    print("f_eval=", T_workers[4])
    print("gen f_eval_SS=", T_workers[5] + T_workers[6])
    print("multiplication=", T_workers[1] + T_workers[2])
    print("communication =", T_workers[6] + T_workers[7] + T_workers[8])
    print("\nPreprocessing in workers (from sum)=", T_workers[0] + T_workers[1] + T_workers[2])
    print("Main Loop total time (from sum)=", np.sum(T_workers[3:9]) - T_workers[7])
    print("\nFrom workers: preprocessing =", T_workers[9])
    print("From workers: Maint Loop =", T_workers[10])
    print("\nN,K,T", N, K, T)

    time_out.append(time_set)

    comm.Barrier()

elif rank <= N:

    def MPI_TruncPr(in_SS_T, r1_SS_T, r2_SS_T, trunc_k, trunc_m, T, p):
        t0 = time.time()
        a_SS_T = in_SS_T.astype("int64")
        trunc_size = np.prod(a_SS_T.shape)

        a_SS_T = np.reshape(a_SS_T, trunc_size)
        r1_SS_T = np.reshape(r1_SS_T, trunc_size)
        r2_SS_T = np.reshape(r2_SS_T, trunc_size)

        t1 = time.time()

        b_SS_T = np.mod(a_SS_T + 2 ** (trunc_k - 1), p)

        r_SS_T = np.mod((2 ** trunc_m) * r2_SS_T + r1_SS_T, p)

        c_SS_T = np.mod(b_SS_T + r_SS_T, p)
        # print "rank=",rank, c_SS_T.shape

        t2 = time.time()

        dec_input = np.empty((T + 1, trunc_size), dtype="int64")
        for j in list(range(1, T + 2)):
            if rank == j:
                dec_input[j - 1, :] = c_SS_T
                for j in list(range(1, rank)) + list(range(rank + 1, N + 1)):  # secret share q
                    data = c_SS_T
                    comm.Send(data, dest=j)  # sent data to worker j
            else:
                data = np.empty(trunc_size, dtype="int64")
                comm.Recv(data, source=j)
                dec_input[j - 1, :] = data  # coefficients for the polynomial

        t3 = time.time()

        c_dec = BGW_decoding(dec_input, list(range(T + 1)), p)
        # print "rank=",rank, "c_dec is completed", c_dec.shape

        t4 = time.time()
        c_prime = np.mod(np.reshape(c_dec, trunc_size), 2 ** trunc_m)

        a_prime_SS_T = np.mod(c_prime - r1_SS_T, p)

        d_SS_T = np.mod(a_SS_T - a_prime_SS_T, p)

        t5 = time.time()
        d_SS_T = divmod(d_SS_T, 2 ** trunc_m, p)

        d_SS_T = np.reshape(d_SS_T, in_SS_T.shape)

        t6 = time.time()
        # time_set = np.array([t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t6-t5])
        # print "time info for trunc pr",time_set
        return d_SS_T.astype("int64")


    K = K_[N_case]  # number of submatrices
    T = T_[N_case]

    m = comm.recv(source=0)  # number of rows =  number of training samples
    d = comm.recv(source=0)  # number of columns  = number of features

    data = np.empty(m * d, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    X_SS_T = np.reshape(data, (m, d))  # coded matrix

    data = np.empty(m * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    y_scale = np.reshape(data, (m, 1))  # coded matrix

    data = np.empty(d * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    w_SS_T = np.reshape(data, (d, 1))  # coded matrix

    data = np.empty(m * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r_SS_T = np.reshape(data, (m, 1))  # coded matrix

    data = np.empty(m * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r_SS_2T = np.reshape(data, (m, 1))  # coded matrix

    data = np.empty(d * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r_mult2_SS_T = np.reshape(data, (d, 1))  # coded matrix

    data = np.empty(d * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r_mult2_SS_2T = np.reshape(data, (d, 1))  # coded matrix

    data = np.empty(d * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r1_SS_T = np.reshape(data, (d, 1))  # coded matrix

    data = np.empty(d * 1, dtype="int64")  # allocate space to receive the matrix
    comm.Recv(data, source=0)
    r2_SS_T = np.reshape(data, (d, 1))  # coded matrix

    data = np.empty(T * (int(m / K)) * d, dtype="int64")
    comm.Recv(data, source=0)
    R_LCC_SS_T = np.reshape(data, (T, int(m / K), d))  # random matrix for LCC encoding of X

    data = np.empty(T * d, dtype="int64")
    comm.Recv(data, source=0)
    r_LCC_SS_T = np.reshape(data, (T, d, 1))  # random matrix for LCC encoding of w

    # print "data received! rank=",rank
    comm.Barrier()

    ############################################
    #       Preprocessing Starts Here.         #
    ############################################

    # Group setting for LCC encoding & decoding
    # each group has (T+1) clients
    if np.mod(N, T + 1) == 0:
        group_id = int(int(rank - 1) / int(T + 1))
        group_idx_set = list(range(group_id * (T + 1), (group_id + 1) * (T + 1)))
    else:
        group_id = int(int(rank - 1) / int(T + 1))
        last_group_id = int(int(N) / int(T + 1))
        if (group_id == last_group_id) | (group_id == last_group_id - 1):
            group_idx_set = list(range((last_group_id - 1) * (T + 1), N))
        else:
            group_idx_set = list(range(group_id * (T + 1), (group_id + 1) * (T + 1)))
    group_stt_idx = group_idx_set[0]
    group_idx_set_others = [idx for idx in group_idx_set if rank - 1 != idx]
    my_worker_idx = rank - 1
    # end of group setting

    ### Preprocessing 1.  LCC encoding of X
    ### input  : X_SS_T (=secret share of X= [X]_i)
    ### output : X_LCC (=\widetiled{X}_i)

    # 1.1. generate the secret share of encoded X
    t0_LCC_encoding_X = time.time()

    X_LCC_T = LCC_encoding_w_Random_partial(X_SS_T, R_LCC_SS_T, N, K, T, p, group_idx_set)

    t_LCC_encoding_X_onlyencoding = time.time() - t0_LCC_encoding_X

    # 1.2. sending the secret share of encoded X
    t0_comm_X_LCC = time.time()
    dec_input = np.empty((len(group_idx_set), (int(m / K)) * d), dtype="int64")

    for j in group_idx_set:
        if my_worker_idx == j:
            dec_input[my_worker_idx - group_stt_idx, :] = np.reshape(X_LCC_T[my_worker_idx - group_stt_idx, :, :],
                                                                     (int(m / K)) * d)
            for idx in group_idx_set_others:
                # print "from",rank," to ",idx+1
                data = np.reshape(X_LCC_T[idx - group_stt_idx, :, :], (int(m / K)) * d)
                comm.Send(data, dest=idx + 1)  # sent data to worker j
        else:
            data = np.empty((int(m / K)) * d, dtype="int64")
            comm.Recv(data, source=j + 1)
            dec_input[j - group_stt_idx, :] = data  # coefficients for the polynomial
    # print "dec_input info (af comm)=",dec_input[:,0]
    t_comm_X_LCC = time.time() - t0_comm_X_LCC

    # 1.3.  reconstruct the secret : get X_LCC
    X_LCC_dec = BGW_decoding(dec_input, group_idx_set, p)
    X_LCC = np.reshape(X_LCC_dec, (int(m / K), d)).astype("int64")

    t_LCC_encoding_X = time.time() - t0_LCC_encoding_X

    print("time info for gen X_LCC", t_LCC_encoding_X_onlyencoding, t_comm_X_LCC, t_LCC_encoding_X)

    # For debugging
    if debugging_X_LCC == 1:
        # print(X_LCC_T.shape)
        # print("X_LCC info:",X_LCC_dec.shape, X_LCC.shape)
        # print(X_LCC_dec[0,0:3])
        # print(X_LCC[0,0:3])
        comm.Send(X_LCC_dec, dest=0)

    ## Preprocessing 2. Calculate common terms
    t0_XTX = time.time()
    # XTX_LCC = np.random.randint(p,size=(d,d)).astype("int64")
    XTX_LCC = X_LCC.T.dot(X_LCC)
    t_XTX = time.time() - t0_XTX

    t0_XTy = time.time()
    c0_m_y = np.int64(2 ** (q_bit_y + coeffs1_exp - coeffs0_exp) - (2 ** coeffs1_exp) * y_scale)
    XTy_SS_T = X_SS_T.T.dot(c0_m_y)
    t_XTy = time.time() - t0_XTy

    t_preprocessing = time.time() - t0_LCC_encoding_X

    ############################################
    #       Preprocessing Ends Here.           #
    ############################################

    ############################################
    #           Main Loop Starts Here.         #
    ############################################

    # set parameters
    iter = 0
    hist_w_SS_T = np.empty((max_iter + 1, d), dtype="int64")
    hist_w_SS_T[0, :] = np.reshape(w_SS_T, d)

    t_LCC_encoding_w, t_f_eval, t_gen_f_SS, t_gen_grad_SS, t_comm_f_eval_SS, t_trunc, t_comm_w = 0, 0, 0, 0, 0, 0, 0
    t0_mainloop = time.time()

    while iter < max_iter:

        iter = iter + 1
        # print("iter=",iter)

        ### 1. LCC encoding of w(t)
        ### input  : w_SS_T (=secret share of w(t)= [w(t)]_i)
        ### output : w_LCC (=\widetiled{w}^{(t)}_i)

        # 1.1 generate the secret share of encoded w
        t0_LCC_encoding_w = time.time()
        w_rep_SS_T = np.transpose(np.tile(np.transpose(w_SS_T), K))  # w_rep: repeated vector with size ( d*K by 1 )
        w_LCC_SS_T = LCC_encoding_w_Random_partial(w_rep_SS_T, r_LCC_SS_T, N, K, T, p, group_idx_set)
        # print(type(w_LCC_SS_T[0,0,0]), np.max(w_LCC_SS_T))

        # 1.2. sending the secret share of encoded w
        dec_input = np.empty((len(group_idx_set), d), dtype="int64")
        t0_comm_w = time.time()
        for j in group_idx_set:
            if my_worker_idx == j:
                dec_input[my_worker_idx - group_stt_idx, :] = np.reshape(
                    w_LCC_SS_T[my_worker_idx - group_stt_idx, :, :], d)
                for idx in group_idx_set_others:
                    # print "from",rank," to ",idx+1
                    data = np.reshape(w_LCC_SS_T[idx - group_stt_idx, :, :], d)
                    comm.Send(data, dest=idx + 1)  # sent data to worker j
            else:
                data = np.empty(d, dtype="int64")
                comm.Recv(data, source=j + 1)
                dec_input[j - group_stt_idx, :] = data  # coefficients for the polynomial
        t_comm_w += time.time() - t0_comm_w

        # 1.3. reconstruct the secret : get w_LCC
        w_LCC_dec = BGW_decoding(dec_input, group_idx_set, p)
        w_LCC = np.reshape(w_LCC_dec, (d, 1)).astype("int64")

        t_LCC_encoding_w += time.time() - t0_LCC_encoding_w

        if debugging_w_LCC == 1:
            # print(w_LCC_dec.shape)
            # print(w_LCC_dec[0,0:3])
            comm.Send(np.reshape(w_LCC_dec, d), dest=0)

        ### 2. compute f over LCC_encoded inputs
        t0_f_eval = time.time()
        f_eval = np.dot(XTX_LCC, w_LCC)
        t_f_eval = + time.time() - t0_f_eval

        ### 3. generate the secret shares of f_eval
        t0_gen_f_SS = time.time()
        f_eval_SS_T = BGW_encoding(f_eval, N, T, p)
        t_gen_f_SS = + time.time() - t0_gen_f_SS
        # print("f_eval:", f_eval.shape, f_eval_SS_T.shape)

        ### 4. LCC decoding f_eval  & calculate the gradient (over the secret share)
        t0_gen_grad_SS = time.time()

        # 4.1. send the secret shares of f_eval
        f_deg = 3
        RT = f_deg * (K + T - 1) + 1
        dec_input = np.empty((RT, d), dtype="int64")
        for j in list(range(1, RT + 1)):
            if rank == j:
                dec_input[j - 1, :] = np.reshape(f_eval_SS_T[j - 1, :, :], d)
                for j in list(range(1, rank)) + list(range(rank + 1, N + 1)):  # secret share q
                    data = np.reshape(f_eval_SS_T[j - 1, :, :], d)
                    comm.Send(data, dest=j)  # sent data to worker j
            else:
                data = np.empty(d, dtype="int64")
                comm.Recv(data, source=j)
                dec_input[j - 1, :] = data  # coefficients for the polynomial
        t_comm_f_eval_SS += time.time() - t0_gen_grad_SS

        # 4.2. decode f_eval over the secret share
        dec_out = LCC_decoding(dec_input, f_deg, N, K, T, list(range(RT)), p)

        # 4.3. update the secret share of gradient
        f_SS_T = np.zeros((d, 1), dtype="int64")
        for j in list(range(K)):
            f_SS_T = np.mod(f_SS_T + np.reshape(dec_out[j, :], (d, 1)), p)
        grad_SS_T = np.mod(f_SS_T + XTy_SS_T, p)

        t_gen_grad_SS += time.time() - t0_gen_grad_SS

        if debugging_f_SS_T:
            comm.Send(np.reshape(f_SS_T, d), dest=0)

        ### 5. truncation gradient
        t0_trunc = time.time()
        grad_trunc_SS_T = MPI_TruncPr(grad_SS_T, r1_SS_T, r2_SS_T, trunc_k, trunc_scale, T, p)
        t_trunc += time.time() - t0_trunc

        ### 6. update the model
        w_SS_T = np.mod(w_SS_T - grad_trunc_SS_T, p)

        if debugging_w_SS_T == 1:
            # print(rank,"debugging_hist_w_SS_T")
            comm.Send(np.reshape(w_SS_T, d), dest=0)

        hist_w_SS_T[iter, :] = np.reshape(w_SS_T, d)

    t_mainloop = time.time() - t0_mainloop

    if debugging_hist_w_SS_T == 1:
        print("debugging_hist_w_SS_T")
        data = np.reshape(hist_w_SS_T, (max_iter + 1) * d)
        comm.Send(data, dest=0)

    # send time_set to rank 0
    time_set = np.array(
        [t_LCC_encoding_X, t_XTX, t_XTy, t_LCC_encoding_w, t_f_eval, t_gen_f_SS, t_comm_w, t_comm_f_eval_SS,
         t_comm_X_LCC, t_preprocessing, t_mainloop])
    comm.Send(time_set, dest=0)

    comm.Barrier()
