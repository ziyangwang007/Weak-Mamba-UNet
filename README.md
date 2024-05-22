<div align="center">
<h1> <b>Weak-Mamba-UNet</b>: <br /> Visual Mamba Makes CNN and ViT Work Better for Scribble-based Medical Image Segmentation </h1>

[![arXiv](https://img.shields.io/badge/arXiv-2402.10887-b31b1b.svg)](https://arxiv.org/abs/2402.10887)

</div>

> This repo provides an implementation of the training and inference pipeline for [Weak-Mamba-UNet](https://arxiv.org/abs/2402.10887). 


## Contents ###
- [Graphical Abstract](#Graphical-Abstract)
- [Results](#Results)
- [Requirements](#Requirements)
- [Usage](#Usage)
- [Reference](#Reference)
- [Contact](#Contact)

 


## Graphical Abstract

The introduction of Scribble Annotation

<img src="img/wslintro.png" width="50%" height="auto">

The proposed Framework

<img src="img/wslframework.png" width="50%" height="auto">


## Results

<img src="img/results.png" width="50%" height="auto">




## Requirements
* Pytorch, MONAI 
* Some basic python packages: Torchio, Numpy, Scikit-image, SimpleITK, Scipy, Medpy, nibabel, tqdm ......

```shell
cd casual-conv1d

python setup.py install
```

```shell
cd mamba

python setup.py install
```



## Usage

1. Clone the repo:
```shell
git clone https://github.com/ziyangwang007/Weak-Mamba-UNet.git
cd Weak-Mamba-UNet
```

2. Download Pretrained Model

Download through [Google Drive](https://drive.google.com/file/d/14RzbbBDjbKbgr0ordKlWbb69EFkHuplr/view?usp=sharing) for SwinUNet, and [[Google Drive]](https://drive.google.com/file/d/1uUPsr7XeqayCxlspqBHbg5zIWx0JYtSX/view?usp=sharing) for Mamba-UNet, and save in `../code/pretrained_ckpt`.

3. Download Dataset


## Reference


## Contact