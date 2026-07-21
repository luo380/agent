"""
FAISS (Facebook AI Similarity Search) 演示代码
==============================================

FAISS 是 Facebook AI Research 开发的高效相似性搜索和向量聚类库。
本演示包含以下核心功能:
1. 基础索引 (IndexFlatL2) - 精确L2距离搜索
2. IVF索引 (IndexIVFFlat) - 基于倒排索引的近似搜索
3. PQ索引 (IndexIVFPQ) - 基于乘积量化的压缩索引
4. 索引保存与加载
5. K-means聚类
6. 不同距离度量对比
7. 批量搜索

运行方式: python faiss_demo.py
"""

import numpy as np
import faiss


def demo_basic_index():
    """
    演示1: 基础索引 IndexFlatL2
    
    IndexFlatL2 是最基础的索引类型，使用暴力搜索(brute-force)方式
    计算查询向量与所有数据库向量的L2距离，返回最近的k个邻居。
    
    特点:
    - 精确搜索，无近似误差
    - 无需训练(training-free)
    - 时间复杂度 O(n)，适合小规模数据
    """
    print("=" * 60)
    print("1. 基础索引演示 - IndexFlatL2 (精确L2距离搜索)")
    print("=" * 60)
    
    # 向量维度
    d = 64
    # 数据库向量数量
    nb = 1000
    # 查询向量数量
    nq = 10
    # 设置随机种子，保证结果可重复
    np.random.seed(1234)
    
    # 生成随机数据库向量，类型必须是 float32
    xb = np.random.random((nb, d)).astype('float32')
    # 给向量添加一些规律性，便于观察结果
    xb[:, 0] += np.arange(nb) / 1000.
    
    # 生成随机查询向量
    xq = np.random.random((nq, d)).astype('float32')
    xq[:, 0] += np.arange(nq) / 1000.
    
    # 创建 IndexFlatL2 索引
    # 参数: d - 向量维度
    index = faiss.IndexFlatL2(d)
    
    # 检查索引是否需要训练
    # IndexFlatL2 不需要训练，所以 is_trained 为 True
    print(f"索引是否训练完成: {index.is_trained}")
    
    # 向索引中添加向量
    index.add(xb)
    # 查看索引中向量总数
    print(f"索引中向量数量: {index.ntotal}")
    
    # 搜索最近邻
    # k - 返回每个查询的前k个最近邻
    k = 4
    # D - 距离矩阵，shape=(nq, k)，   
    # I - 索引矩阵，shape=(nq, k)，存储数据库中向量的索引
    D, I = index.search(xq, k)
    
    # 打印第一个查询向量的搜索结果
    print("\n查询向量 0 的最近邻索引:")
    print(I[0])  # 输出: [250 310 439 542] - 表示最近的4个向量在数据库中的索引
    print("\n查询向量 0 的最近邻距离:")
    print(D[0])  # 输出: 对应的L2距离值
    
    return index


def demo_flat_ip_index():
    """
    演示2: 基础索引 IndexFlatIP (精确内积搜索)
    
    IndexFlatIP 使用内积(Inner Product)作为距离度量，与 IndexFlatL2 类似，
    但它计算的是向量之间的点积而不是欧氏距离。
    
    内积公式: dot(a, b) = a·b = Σ(a[i] * b[i])
    
    特点:
    - 精确搜索，无近似误差
    - 无需训练
    - 内积越大表示向量越相似
    - 常用于计算向量相似度、推荐系统等场景
    """
    print("\n" + "=" * 60)
    print("2. 基础索引演示 - IndexFlatIP (精确内积搜索)")
    print("=" * 60)
    
    # 向量维度
    d = 64
    # 数据库向量数量
    nb = 1000
    # 查询向量数量
    nq = 10
    # 设置随机种子，保证结果可重复
    np.random.seed(1234)
    
    # 生成随机数据库向量，类型必须是 float32
    xb = np.random.random((nb, d)).astype('float32')
    # 给向量添加一些规律性，便于观察结果
    xb[:, 0] += np.arange(nb) / 1000.
    
    # 生成随机查询向量
    xq = np.random.random((nq, d)).astype('float32')
    xq[:, 0] += np.arange(nq) / 1000.
    
    # 创建 IndexFlatIP 索引
    # 参数: d - 向量维度
    index = faiss.IndexFlatIP(d)
    
    # IndexFlatIP 也不需要训练
    print(f"索引是否训练完成: {index.is_trained}")
    
    # 向索引中添加向量
    index.add(xb)
    print(f"索引中向量数量: {index.ntotal}")
    
    # 搜索最近邻
    k = 4
    # D - 内积矩阵，shape=(nq, k)，存储内积值
    # I - 索引矩阵，shape=(nq, k)，存储数据库中向量的索引
    D, I = index.search(xq, k)
    
    # 打印第一个查询向量的搜索结果
    print("\n查询向量 0 的最近邻索引:")
    print(I[0])  # 内积最大的4个向量索引
    print("\n查询向量 0 的最近邻内积值:")
    print(D[0])  # 内积值，越大表示越相似
    
    # 重要区别说明
    print("\n【重要区别】")
    print("L2距离: 值越小表示越相似")
    print("内积(IP): 值越大表示越相似")
    
    return index


def demo_ivf_index():
    """
    演示3: IVF索引 IndexIVFFlat
    
    IVF (Inverted File) 倒排文件索引，将向量空间划分为nlist个 Voronoi 单元。
    查询时只搜索与查询向量最接近的nprobe个单元，实现近似搜索。
    
    特点:
    - 需要训练(training required)
    - 时间复杂度 O(n/nlist)，适合中等规模数据
    - 通过调节 nprobe 控制精度和速度的权衡
    """
    print("\n" + "=" * 60)
    print("3. IVF 索引演示 - IndexIVFFlat (倒排索引近似搜索)")
    print("=" * 60)
    
    d = 64
    nb = 1000
    nq = 10
    np.random.seed(1234)
    
    xb = np.random.random((nb, d)).astype('float32')
    xb[:, 0] += np.arange(nb) / 1000.
    
    xq = np.random.random((nq, d)).astype('float32')
    xq[:, 0] += np.arange(nq) / 1000.
    
    # IVF参数设置
    nlist = 100  # 将向量空间划分为100个簇
    
    # 第一步: 创建量化器(quantizer)
    # 量化器用于确定每个向量属于哪个簇
    quantizer = faiss.IndexFlatL2(d)
    
    # 第二步: 创建 IndexIVFFlat 索引
    # 参数: quantizer(量化器), d(维度), nlist(簇数量), metric(距离度量)
    index = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_L2)
    
    # IVF索引需要训练
    print(f"索引是否训练完成: {index.is_trained}")  # 输出: False
    
    # 训练索引，使用数据库向量作为训练数据
    index.train(xb)
    print(f"训练后索引是否训练完成: {index.is_trained}")  # 输出: True
    
    # 添加向量到索引
    index.add(xb)
    print(f"索引中向量数量: {index.ntotal}")
    
    # 设置搜索时查询的簇数量
    # nprobe 越大，搜索越精确，但速度越慢
    # nprobe <= nlist
    index.nprobe = 10
    
    k = 4
    D, I = index.search(xq, k)
    
    print("\n查询向量 0 的最近邻索引:")
    print(I[0])
    print("\n查询向量 0 的最近邻距离:")
    print(D[0])
    
    return index


def demo_pq_index():
    """
    演示4: PQ索引 IndexIVFPQ
    
    PQ (Product Quantization) 乘积量化，将向量维度分成m段，每段独立量化。
    可以大幅压缩向量存储空间，适合大规模数据。
    
    特点:
    - 需要训练
    - 高压缩率，节省内存
    - 速度非常快
    - 有一定的近似误差
    """
    print("\n" + "=" * 60)
    print("4. PQ 索引演示 - IndexIVFPQ (乘积量化压缩索引)")
    print("=" * 60)
    
    d = 64
    nb = 1000
    nq = 10
    np.random.seed(1234)
    
    xb = np.random.random((nb, d)).astype('float32')
    xb[:, 0] += np.arange(nb) / 1000.
    
    xq = np.random.random((nq, d)).astype('float32')
    xq[:, 0] += np.arange(nq) / 1000.
    
    # PQ参数设置
    nlist = 100  # IVF簇数量
    m = 8       # 将向量分成8段
    k = 4
    
    # 创建量化器和索引
    quantizer = faiss.IndexFlatL2(d)
    # IndexIVFPQ 参数: quantizer, d, nlist, m, bits_per_subvector
    # bits_per_subvector: 每个子向量的量化位数，通常为8(256个 centroids)
    index = faiss.IndexIVFPQ(quantizer, d, nlist, m, 8)
    
    # 训练索引
    index.train(xb)
    # 添加向量
    index.add(xb)
    
    # 设置搜索参数
    index.nprobe = 10
    
    D, I = index.search(xq, k)
    
    print("\n查询向量 0 的最近邻索引:")
    print(I[0])
    print("\n查询向量 0 的最近邻距离:")
    print(D[0])
    
    return index


def demo_index_io(index):
    """
    演示5: 索引保存与加载
    
    FAISS 支持将索引保存到磁盘，便于持久化存储和后续使用。
    """
    print("\n" + "=" * 60)
    print("5. 索引保存与加载")
    print("=" * 60)
    
    # 保存索引到文件
    index_path = "faiss_index.bin"
    faiss.write_index(index, index_path)
    print(f"索引已保存到 {index_path}")
    
    # 从文件加载索引
    index_loaded = faiss.read_index(index_path)
    print(f"从 {index_path} 加载索引")
    
    # 使用加载的索引进行搜索
    d = 64
    nq = 5
    xq = np.random.random((nq, d)).astype('float32')
    
    k = 3
    D, I = index_loaded.search(xq, k)
    print("\n加载后的索引查询结果:")
    print("索引:\n", I)
    print("距离:\n", D)
    
    # 清理临时文件
    import os
    os.remove(index_path)
    print(f"\n临时文件 {index_path} 已删除")


def demo_clustering():
    """
    演示6: K-means 聚类
    
    FAISS 提供高效的 K-means 聚类实现，支持大规模数据。
    """
    print("\n" + "=" * 60)
    print("5. K-means 聚类演示")
    print("=" * 60)
    
    # 数据参数
    d = 32        # 向量维度
    n = 1000      # 数据点数量
    np.random.seed(1234)
    
    # 生成随机数据
    x = np.random.random((n, d)).astype('float32')
    
    # K-means参数
    k = 10        # 聚类数量
    # 创建 K-means 对象
    # 参数: d(维度), k(聚类数), niter(迭代次数), verbose(是否打印详细信息)
    km = faiss.Kmeans(d, k, niter=20, verbose=True)
    
    # 执行聚类
    km.train(x)
    
    # 输出结果
    print("\n聚类中心形状:", km.centroids.shape)  # 输出: (10, 32)
    print("最终损失:", km.obj[-1])  # 最终迭代的目标函数值
    
    # 使用聚类中心作为索引，查询前5个点属于哪个簇
    D, I = km.index.search(x[:5], 1)
    print("\n前 5 个向量的聚类标签:")
    print(I.flatten())  # 输出每个点所属的簇索引


def demo_metrics():
    """
    演示7: 不同距离度量
    
    FAISS 支持多种距离度量:
    - METRIC_L2: L2欧氏距离 (默认)
    - METRIC_INNER_PRODUCT: 内积 (点积)
    - 余弦相似度可以通过对内积搜索的向量归一化实现
    """
    print("\n" + "=" * 60)
    print("6. 不同距离度量演示")
    print("=" * 60)
    
    d = 16
    nb = 100
    nq = 5
    
    np.random.seed(4321)
    xb = np.random.random((nb, d)).astype('float32')
    xq = np.random.random((nq, d)).astype('float32')
    
    # L2 距离索引
    index_l2 = faiss.IndexFlatL2(d)
    index_l2.add(xb)
    
    # 内积索引 (Inner Product)
    index_ip = faiss.IndexFlatIP(d)
    index_ip.add(xb)
    
    k = 3
    D_l2, I_l2 = index_l2.search(xq, k)
    D_ip, I_ip = index_ip.search(xq, k)
    
    print("L2 距离查询结果:")
    print("索引:\n", I_l2[0])
    print("距离:\n", D_l2[0])
    
    print("\n内积查询结果:")
    print("索引:\n", I_ip[0])
    print("距离:\n", D_ip[0])
    
    # 注意: 
    # L2距离越小表示越相似
    # 内积越大表示越相似
    # 因此两种度量的搜索结果可能不同


def demo_batch_search():
    """
    演示8: 批量搜索
    
    FAISS 支持一次查询多个向量，返回批量结果。
    """
    print("\n" + "=" * 60)
    print("7. 批量搜索演示")
    print("=" * 60)
    
    d = 64
    nb = 1000
    nq = 100  # 批量查询100个向量
    np.random.seed(1234)
    
    xb = np.random.random((nb, d)).astype('float32')
    xq = np.random.random((nq, d)).astype('float32')
    
    index = faiss.IndexFlatL2(d)
    index.add(xb)
    
    k = 5
    # 批量搜索，一次处理100个查询向量
    D, I = index.search(xq, k)
    
    # 输出结果形状
    print(f"查询数量: {nq}")
    print(f"每个查询返回 {k} 个结果")
    print(f"距离矩阵形状: {D.shape}")    # 输出: (100, 5)
    print(f"索引矩阵形状: {I.shape}")     # 输出: (100, 5)
    
    # 打印前3个查询的结果
    print("\n前 3 个查询的最近邻索引:")
    for i in range(3):
        print(f"查询 {i}: {I[i]}")


if __name__ == "__main__":
    """
    主函数: 依次运行所有演示
    """
    print("FAISS (Facebook AI Similarity Search) Demo")
    print("=" * 60)
    
    # 运行各个演示
    basic_index = demo_basic_index()   # 基础索引 - IndexFlatL2
    demo_flat_ip_index()               # 基础索引 - IndexFlatIP
    demo_ivf_index()                   # IVF索引
    demo_pq_index()                    # PQ索引
    demo_index_io(basic_index)         # 索引保存加载
    demo_clustering()                  # K-means聚类
    demo_metrics()                     # 距离度量对比
    demo_batch_search()                # 批量搜索
    
    print("\n" + "=" * 60)
    print("FAISS Demo 完成!")
    print("=" * 60)
    print("\nFAISS 主要功能总结:")
    print("- IndexFlatL2: 精确 L2 距离搜索 (适合小规模)")
    print("- IndexFlatIP: 精确内积搜索 (适合计算相似度)")
    print("- IndexIVFFlat: 基于倒排索引的近似搜索 (适合中等规模)")
    print("- IndexIVFPQ: 基于乘积量化的压缩索引 (适合大规模/内存受限)")
    print("- Kmeans: 高效向量聚类")
    print("- 支持索引保存/加载 (持久化存储)")
    print("- 支持批量搜索 (一次查询多个向量)")
    print("\n注意事项:")
    print("1. FAISS 向量必须是 float32 类型")
    print("2. IVF/PQ 索引需要先训练再添加向量")
    print("3. nprobe 越大精度越高但速度越慢")
    print("4. L2距离越小越相似，内积越大越相似")