import argparse
import logging
import os
import random
import shutil
import sys
import time

import numpy as np
import torch
import torch.backends.cudnn as cudnn
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from tensorboardX import SummaryWriter
from torch.nn import BCEWithLogitsLoss
from torch.nn.modules.loss import CrossEntropyLoss
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.utils import make_grid
from tqdm import tqdm

from dataloaders import utils
from dataloaders.dataset import BaseDataSets, RandomGenerator
from networks.net_factory import net_factory
from utils import losses, metrics, ramps
from val_2D import test_single_volume, test_single_volume_ds


from config import get_config
from networks.vision_transformer import SwinUnet as ViT_seg
from networks.vision_mamba import MambaUnet as ViM_seg

from torchsummary import summary

parser = argparse.ArgumentParser()
parser.add_argument('--root_path', type=str,
                    default='../data/ACDC', help='Name of Experiment')
parser.add_argument('--exp', type=str,
                    default='weak_mamba_unet', help='experiment_name')
parser.add_argument('--fold', type=str,
                    default='fold1', help='cross validation')
parser.add_argument('--sup_type', type=str,
                    default='scribble', help='supervision type')
parser.add_argument('--model', type=str,
                    default='unet', help='model_name')
parser.add_argument('--num_classes', type=int,  default=4,
                    help='output channel of network')
parser.add_argument('--max_iterations', type=int,
                    default=30000, help='maximum epoch number to train')
parser.add_argument('--batch_size', type=int, default=12,
                    help='batch_size per gpu')
parser.add_argument('--deterministic', type=int,  default=1,
                    help='whether use deterministic training')
parser.add_argument('--base_lr', type=float,  default=0.01,
                    help='segmentation network learning rate')
parser.add_argument('--patch_size', type=list,  default=[224, 224],
                    help='patch size of network input')
parser.add_argument('--seed', type=int,  default=2022, help='random seed')



parser.add_argument(
    '--cfg', type=str, default="../code/configs/swin_tiny_patch4_window7_224_lite.yaml", help='path to config file', )
# parser.add_argument(
#     '--cfg', type=str, default="../code/configs/vmamba_tiny.yaml", help='path to config file', )

parser.add_argument(
    "--opts",
    help="Modify config options by adding 'KEY VALUE' pairs. ",
    default=None,
    nargs='+',
)
parser.add_argument('--zip', action='store_true',
                    help='use zipped dataset instead of folder dataset')
parser.add_argument('--cache-mode', type=str, default='part', choices=['no', 'full', 'part'],
                    help='no: no cache, '
                    'full: cache all data, '
                    'part: sharding the dataset into nonoverlapping pieces and only cache one piece')
parser.add_argument('--resume', help='resume from checkpoint')
parser.add_argument('--accumulation-steps', type=int,
                    help="gradient accumulation steps")
parser.add_argument('--use-checkpoint', action='store_true',
                    help="whether to use gradient checkpointing to save memory")
parser.add_argument('--amp-opt-level', type=str, default='O1', choices=['O0', 'O1', 'O2'],
                    help='mixed precision opt level, if O0, no amp is used')
parser.add_argument('--tag', help='tag of experiment')
parser.add_argument('--eval', action='store_true',
                    help='Perform evaluation only')
parser.add_argument('--throughput', action='store_true',
                    help='Test throughput only')



args1 = parser.parse_args()

config1 = get_config(args1)







parser2 = argparse.ArgumentParser()
parser2.add_argument('--root_path', type=str,
                    default='../data/ACDC', help='Name of Experiment')
parser2.add_argument('--exp', type=str,
                    default='semi_mamba_unet', help='experiment_name')
parser2.add_argument('--fold', type=str,
                    default='fold1', help='cross validation')
parser2.add_argument('--sup_type', type=str,
                    default='scribble', help='supervision type')
parser2.add_argument('--model', type=str,
                    default='unet', help='model_name')
parser2.add_argument('--num_classes', type=int,  default=4,
                    help='output channel of network')
parser2.add_argument('--max_iterations', type=int,
                    default=60000, help='maximum epoch number to train')
parser2.add_argument('--batch_size', type=int, default=12,
                    help='batch_size per gpu')
parser2.add_argument('--deterministic', type=int,  default=1,
                    help='whether use deterministic training')
parser2.add_argument('--base_lr', type=float,  default=0.01,
                    help='segmentation network learning rate')
parser2.add_argument('--patch_size', type=list,  default=[224, 224],
                    help='patch size of network input')
parser2.add_argument('--seed', type=int,  default=2022, help='random seed')



# parser2.add_argument(
#     '--cfg', type=str, default="../code/configs/swin_tiny_patch4_window7_224_lite.yaml", help='path to config file', )
parser2.add_argument(
    '--cfg', type=str, default="../code/configs/vmamba_tiny.yaml", help='path to config file', )

parser2.add_argument(
    "--opts",
    help="Modify config options by adding 'KEY VALUE' pairs. ",
    default=None,
    nargs='+',
)
parser2.add_argument('--zip', action='store_true',
                    help='use zipped dataset instead of folder dataset')
parser2.add_argument('--cache-mode', type=str, default='part', choices=['no', 'full', 'part'],
                    help='no: no cache, '
                    'full: cache all data, '
                    'part: sharding the dataset into nonoverlapping pieces and only cache one piece')
parser2.add_argument('--resume', help='resume from checkpoint')
parser2.add_argument('--accumulation-steps', type=int,
                    help="gradient accumulation steps")
parser2.add_argument('--use-checkpoint', action='store_true',
                    help="whether to use gradient checkpointing to save memory")
parser2.add_argument('--amp-opt-level', type=str, default='O1', choices=['O0', 'O1', 'O2'],
                    help='mixed precision opt level, if O0, no amp is used')
parser2.add_argument('--tag', help='tag of experiment')
parser2.add_argument('--eval', action='store_true',
                    help='Perform evaluation only')
parser2.add_argument('--throughput', action='store_true',
                    help='Test throughput only')

args2 = parser2.parse_args()


config2 = get_config(args2)


def get_current_consistency_weight(epoch):
    # Consistency ramp-up from https://arxiv.org/abs/1610.02242
    return 1.0 * ramps.sigmoid_rampup(epoch, 60)


def update_ema_variables(model, ema_model, alpha, global_step):
    # Use the true average until the exponential average is more correct
    alpha = min(1 - 1 / (global_step + 1), alpha)
    for ema_param, param in zip(ema_model.parameters(), model.parameters()):
        ema_param.data.mul_(alpha).add_(1 - alpha, param.data)


def train(args, snapshot_path):
    base_lr = args.base_lr
    num_classes = args.num_classes
    batch_size = args.batch_size
    max_iterations = args.max_iterations

    def create_model(ema=False):
        # Network definition
        model = net_factory(net_type=args.model, in_chns=1,
                            class_num=num_classes)
        if ema:
            for param in model.parameters():
                param.detach_()
        return model

    modelA = ViT_seg(config1, img_size=args.patch_size,
                     num_classes=args.num_classes).cuda()
    modelA.load_from(config1)
    
    modelB = ViM_seg(config2, img_size=args.patch_size,
                     num_classes=args.num_classes).cuda()
    modelB.load_from(config2)

    modelC = create_model()

    db_train = BaseDataSets(base_dir=args.root_path, split="train", transform=transforms.Compose([
        RandomGenerator(args.patch_size)
    ]), fold=args.fold, sup_type=args.sup_type)
    db_val = BaseDataSets(base_dir=args.root_path,
                          fold=args.fold, split="val")

    def worker_init_fn(worker_id):
        random.seed(args.seed + worker_id)

    trainloader = DataLoader(db_train, batch_size=batch_size, shuffle=True,
                             num_workers=8, pin_memory=True, worker_init_fn=worker_init_fn)
    valloader = DataLoader(db_val, batch_size=1, shuffle=False,
                           num_workers=1)

    modelA.train()
    modelB.train()
    modelC.train()

    optimizerA = optim.SGD(modelA.parameters(), lr=base_lr,
                          momentum=0.9, weight_decay=0.0001)
    optimizerB = optim.SGD(modelB.parameters(), lr=base_lr,
                          momentum=0.9, weight_decay=0.0001)
    optimizerC = optim.SGD(modelC.parameters(), lr=base_lr,
                          momentum=0.9, weight_decay=0.0001)

    ce_loss = CrossEntropyLoss(ignore_index=4)
    dice_loss = losses.DiceLoss(num_classes)


    writer = SummaryWriter(snapshot_path + '/log')
    logging.info("{} iterations per epoch".format(len(trainloader)))

    iter_num = 0
    max_epoch = max_iterations // len(trainloader) + 1
    best_performance1 = 0.0
    best_performance2 = 0.0
    best_performance3 = 0.0
    iterator = tqdm(range(max_epoch), ncols=70)
    for epoch_num in iterator:
        for i_batch, sampled_batch in enumerate(trainloader):

            volume_batch, label_batch = sampled_batch['image'], sampled_batch['label']
            volume_batch, label_batch = volume_batch.cuda(), label_batch.cuda()

            outputsA = modelA(volume_batch)
            outputs_softA = torch.softmax(outputsA, dim=1)
            loss_ceA = ce_loss(outputsA, label_batch.long())

            outputsB = modelB(volume_batch)
            outputs_softB = torch.softmax(outputsB, dim=1)
            loss_ceB = ce_loss(outputsB, label_batch.long())

            outputsC = modelC(volume_batch)
            outputs_softC = torch.softmax(outputsC, dim=1)
            loss_ceC = ce_loss(outputsC, label_batch.long())


            consistency_weight = get_current_consistency_weight(iter_num // 1000)


            point1 = random.random()
            point2 = random.random()

            # Ensure point1 is less than point2
            if point1 > point2:
                point1, point2 = point2, point1

            # Calculate the lengths of the segments
            alpha = point1
            beta = point2 - point1
            gamma = 1 - point2

            pseudo_supervision = torch.argmax(
                (alpha * outputs_softA + beta * outputs_softB + gamma * outputs_softC), dim=1)

            loss_pse_supA = dice_loss(outputs_softA, pseudo_supervision.unsqueeze(1)) 

            loss_pse_supB = dice_loss(outputs_softB, pseudo_supervision.unsqueeze(1))

            loss_pse_supC = dice_loss(outputs_softC, pseudo_supervision.unsqueeze(1))


            model1_loss = loss_ceA + loss_pse_supA
            model2_loss = loss_ceB + loss_pse_supB
            model3_loss = loss_ceC + loss_pse_supC           

            loss = model1_loss + model2_loss + model3_loss


            optimizerA.zero_grad()
            optimizerB.zero_grad()
            optimizerC.zero_grad()

            loss.backward()

            optimizerA.step()
            optimizerB.step()
            optimizerC.step()



            iter_num = iter_num + 1

            lr_ = base_lr * (1.0 - iter_num / max_iterations) ** 0.9
            for param_group in optimizerA.param_groups:
                param_group['lr'] = lr_
            for param_group in optimizerB.param_groups:
                param_group['lr'] = lr_

            writer.add_scalar('info/lr', lr_, iter_num)

            writer.add_scalar('loss/model1_loss',
                              model1_loss, iter_num)
            writer.add_scalar('loss/model2_loss',
                              model2_loss, iter_num)
            writer.add_scalar('loss/model3_loss',
                              model3_loss, iter_num)

            logging.info(
                'iteration %d : loss : %f, loss_ceA: %f, loss_ceB: %f, loss_ceC: %f,' %
                (iter_num, loss.item(), loss_ceA.item(), loss_ceB.item(), loss_ceC.item()))

            if iter_num % 20 == 0:
                image = volume_batch[0, 0:1, :, :]
                image = (image - image.min()) / (image.max() - image.min())
                writer.add_image('train/Image', image, iter_num)
                outputsA = torch.argmax(torch.softmax(
                    outputsA, dim=1), dim=1, keepdim=True)
                writer.add_image('train/model1_Prediction',
                                 outputsA[0, ...] * 50, iter_num)

                outputsB = torch.argmax(torch.softmax(
                    outputsB, dim=1), dim=1, keepdim=True)
                writer.add_image('train/model2_Prediction',
                                 outputsB[0, ...] * 50, iter_num)
                labs = label_batch[0, ...].unsqueeze(0) * 50
                writer.add_image('train/GroundTruth', labs, iter_num)

                outputsC = torch.argmax(torch.softmax(
                    outputsC, dim=1), dim=1, keepdim=True)
                writer.add_image('train/model3_Prediction',
                                 outputsC[0, ...] * 50, iter_num)
                labs = label_batch[0, ...].unsqueeze(0) * 50
                writer.add_image('train/GroundTruth', labs, iter_num)

            if iter_num > 0 and iter_num % 200 == 0:
                modelA.eval()
                metric_list = 0.0
                for i_batch, sampled_batch in enumerate(valloader):
                    metric_i = test_single_volume(
                        sampled_batch["image"], sampled_batch["label"], modelA, classes=num_classes, patch_size=args.patch_size)
                    metric_list += np.array(metric_i)
                metric_list = metric_list / len(db_val)
                for class_i in range(num_classes-1):
                    writer.add_scalar('info/model1_val_{}_dice'.format(class_i+1),
                                      metric_list[class_i, 0], iter_num)
                    writer.add_scalar('info/model1_val_{}_hd95'.format(class_i+1),
                                      metric_list[class_i, 1], iter_num)

                performance1 = np.mean(metric_list, axis=0)[0]

                mean_hd951 = np.mean(metric_list, axis=0)[1]
                writer.add_scalar('info/model1_val_mean_dice', performance1, iter_num)
                writer.add_scalar('info/model1_val_mean_hd95', mean_hd951, iter_num)

                if performance1 > best_performance1:
                    best_performance1 = performance1
                    save_mode_path = os.path.join(snapshot_path,
                                                  'model1_iter_{}_dice_{}.pth'.format(
                                                      iter_num, round(best_performance1, 4)))
                    save_best = os.path.join(snapshot_path,
                                             'ViT_best_model.pth')
                    torch.save(modelA.state_dict(), save_mode_path)
                    torch.save(modelA.state_dict(), save_best)

                logging.info(
                    'model1_iteration %d : mean_dice : %f mean_hd95 : %f' % (iter_num, performance1, mean_hd951))
                modelA.train()





                modelB.eval()
                metric_list = 0.0
                for i_batch, sampled_batch in enumerate(valloader):
                    metric_i = test_single_volume(
                        sampled_batch["image"], sampled_batch["label"], modelB, classes=num_classes, patch_size=args.patch_size)
                    metric_list += np.array(metric_i)
                metric_list = metric_list / len(db_val)
                for class_i in range(num_classes-1):
                    writer.add_scalar('info/model2_val_{}_dice'.format(class_i+1),
                                      metric_list[class_i, 0], iter_num)
                    writer.add_scalar('info/model2_val_{}_hd95'.format(class_i+1),
                                      metric_list[class_i, 1], iter_num)

                performance2 = np.mean(metric_list, axis=0)[0]
                mean_hd952 = np.mean(metric_list, axis=0)[1]
                writer.add_scalar('info/model2_val_mean_dice', performance2, iter_num)
                writer.add_scalar('info/model2_val_mean_hd95', mean_hd952, iter_num)

                if performance2 > best_performance2:
                    best_performance2 = performance2
                    save_mode_path = os.path.join(snapshot_path,
                                                  'model2_iter_{}_dice_{}.pth'.format(
                                                      iter_num, round(best_performance2, 4)))
                    save_best = os.path.join(snapshot_path,
                                             'UNet_best_model.pth')
                    torch.save(modelB.state_dict(), save_mode_path)
                    torch.save(modelB.state_dict(), save_best)

                logging.info(
                    'model2_iteration %d : mean_dice : %f mean_hd95 : %f' % (iter_num, performance2, mean_hd952))
                modelB.train()





                modelC.eval()
                metric_list = 0.0
                for i_batch, sampled_batch in enumerate(valloader):
                    metric_i = test_single_volume(
                        sampled_batch["image"], sampled_batch["label"], modelC, classes=num_classes, patch_size=args.patch_size)
                    metric_list += np.array(metric_i)
                metric_list = metric_list / len(db_val)
                for class_i in range(num_classes-1):
                    writer.add_scalar('info/model3_val_{}_dice'.format(class_i+1),
                                      metric_list[class_i, 0], iter_num)
                    writer.add_scalar('info/model3_val_{}_hd95'.format(class_i+1),
                                      metric_list[class_i, 1], iter_num)

                performance3 = np.mean(metric_list, axis=0)[0]
                mean_hd953 = np.mean(metric_list, axis=0)[1]
                writer.add_scalar('info/model3_val_mean_dice', performance3, iter_num)
                writer.add_scalar('info/model3_val_mean_hd95', mean_hd953, iter_num)

                if performance3 > best_performance3:
                    best_performance3 = performance3
                    save_mode_path = os.path.join(snapshot_path,
                                                  'model3_iter_{}_dice_{}.pth'.format(
                                                      iter_num, round(best_performance3, 4)))
                    save_best = os.path.join(snapshot_path,
                                             'UNet_best_model.pth')
                    torch.save(modelC.state_dict(), save_mode_path)
                    torch.save(modelC.state_dict(), save_best)

                logging.info(
                    'model3_iteration %d : mean_dice : %f mean_hd95 : %f' % (iter_num, performance3, mean_hd953))
                modelC.train()

            if iter_num % 3000 == 0:
                save_mode_path = os.path.join(
                    snapshot_path, 'model1_iter_' + str(iter_num) + '.pth')
                torch.save(modelA.state_dict(), save_mode_path)
                logging.info("save model1 to {}".format(save_mode_path))

                save_mode_path = os.path.join(
                    snapshot_path, 'model2_iter_' + str(iter_num) + '.pth')
                torch.save(modelB.state_dict(), save_mode_path)
                logging.info("save model2 to {}".format(save_mode_path))

                save_mode_path = os.path.join(
                    snapshot_path, 'model3_iter_' + str(iter_num) + '.pth')
                torch.save(modelC.state_dict(), save_mode_path)
                logging.info("save model3 to {}".format(save_mode_path))


            if iter_num >= max_iterations:
                break
        if iter_num >= max_iterations:
            iterator.close()
            break
    writer.close()
    return "Training Finished!"


if __name__ == "__main__":
    if not args1.deterministic:
        cudnn.benchmark = True
        cudnn.deterministic = False
    else:
        cudnn.benchmark = False
        cudnn.deterministic = True

    random.seed(args1.seed)
    np.random.seed(args1.seed)
    torch.manual_seed(args1.seed)
    torch.cuda.manual_seed(args1.seed)

    snapshot_path = "../model/{}_{}/{}".format(
        args1.exp, args1.fold, args1.sup_type)
    if not os.path.exists(snapshot_path):
        os.makedirs(snapshot_path)
    if os.path.exists(snapshot_path + '/code_prostate'):
        shutil.rmtree(snapshot_path + '/code_prostate')
    shutil.copytree('.', snapshot_path + '/code_prostate',
                    shutil.ignore_patterns(['.git', '__pycache__']))

    logging.basicConfig(filename=snapshot_path+"/log.txt", level=logging.INFO,
                        format='[%(asctime)s.%(msecs)03d] %(message)s', datefmt='%H:%M:%S')
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    logging.info(str(args1))
    train(args1, snapshot_path)
